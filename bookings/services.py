"""Бізнес-логіка бронювань.

Усі зміни бронювань проходять через функції цього модуля, а не напряму
через модель: тут перевіряються права, допустимі переходи статусів
і пишеться журнал подій (BookingEvent).
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, OperationalError, transaction

from catalog.models import EquipmentUnit, Tariff

from .models import Booking, BookingEvent


class BookingError(Exception):
    """Помилка, яку можна показати користувачеві як є."""


class BookingConflict(BookingError):
    """Екземпляр уже зайнятий на частину періоду."""


# Доплата за кожну добу запізнення = ціна доби із заявки × коефіцієнт.
LATE_FEE_MULTIPLIER = Decimal("1.5")

# SQLSTATE помилки PostgreSQL «deadlock detected».
DEADLOCK_DETECTED = "40P01"
CREATE_ATTEMPTS = 3


def is_deadlock(exc: OperationalError) -> bool:
    return getattr(exc.__cause__, "sqlstate", None) == DEADLOCK_DETECTED


# Допустимі переходи статусів: зі стану -> {новий стан: хто може}.
# Погодження вручну немає: заявка, що пройшла перевірки, одразу «Підтверджено».
TRANSITIONS = {
    Booking.Status.CONFIRMED: {
        Booking.Status.ISSUED: "manager",
        Booking.Status.CANCELLED: "owner_or_manager",
    },
    Booking.Status.ISSUED: {
        Booking.Status.RETURNED: "manager",
    },
}


def current_tariff(equipment_type, on_date: date) -> Tariff | None:
    """Тариф типу обладнання, чинний на дату (останній з valid_from <= on_date)."""
    return (
        Tariff.objects.filter(equipment_type=equipment_type, valid_from__lte=on_date)
        .order_by("-valid_from")
        .first()
    )


def tariff_for(unit: EquipmentUnit, on_date: date) -> Tariff:
    """Тариф для екземпляра на дату початку оренди; помилка, якщо тарифу немає."""
    tariff = current_tariff(unit.equipment_type, on_date)
    if tariff is None:
        raise BookingError("Для цього обладнання не задано тариф на вибрану дату.")
    return tariff


def calculate_price(price_per_day: Decimal, start: date, end: date) -> Decimal:
    """Вартість = кількість діб × ціна за добу.

    Період напіввідкритий [start; end): день повернення не оплачується.
    Тарифікація подобова, тому неповних діб не буває — округлення не потрібне.
    """
    days = (end - start).days
    if days <= 0:
        raise BookingError("Дата повернення має бути пізніше за дату видачі.")
    return (price_per_day * days).quantize(Decimal("0.01"))


def validate_period(start: date, end: date, today: date | None = None) -> None:
    today = today or date.today()
    if start < today:
        raise BookingError("Не можна забронювати обладнання на минулу дату.")
    if end <= start:
        raise BookingError("Дата повернення має бути пізніше за дату видачі.")


def create_booking(*, client, unit: EquipmentUnit, start: date, end: date) -> Booking:
    """Створює бронювання й одразу підтверджує його.

    Ручного погодження немає: якщо будь-яка перевірка не пройшла
    (дати, стан екземпляра, тариф, перетин), система відхиляє заявку
    винятком BookingError і нічого не зберігає.

    Перетин інтервалів остаточно перевіряє обмеження booking_no_overlap_per_unit
    у PostgreSQL. Попередня перевірка в Python потрібна лише для зрозумілого
    повідомлення; на неї не покладаємось, бо між перевіркою й записом
    інший запит може встигнути зайняти екземпляр.

    Взаємне блокування. Коли дві транзакції одночасно вставляють бронювання
    на той самий період, кожна бачить незавершений запис іншої й чекає на неї.
    PostgreSQL виявляє це (deadlock) і перериває одну з них. Перервану спробу
    повторюємо: друга спроба вже бачить завершене бронювання й отримує
    звичайний BookingConflict замість помилки сервера.
    """
    validate_period(start, end)
    if unit.status != EquipmentUnit.Status.AVAILABLE:
        raise BookingError("Цей екземпляр зараз недоступний для оренди.")

    tariff = tariff_for(unit, start)
    total = calculate_price(tariff.price_per_day, start, end)
    buffer_days = unit.equipment_type.turnaround_days

    for attempt in range(1, CREATE_ATTEMPTS + 1):
        try:
            return _insert_booking(client, unit, start, end, tariff.price_per_day, total, buffer_days)
        except OperationalError as exc:
            if not is_deadlock(exc) or attempt == CREATE_ATTEMPTS:
                raise
        except IntegrityError as exc:
            if "booking_no_overlap_per_unit" in str(exc):
                message = "Цей екземпляр уже заброньовано на частину вибраного періоду."
                if buffer_days:
                    message += (
                        f" Враховується технічна перерва: {buffer_days} дн. після кожної оренди."
                    )
                raise BookingConflict(message) from exc
            raise


def _insert_booking(client, unit, start, end, price_per_day, total, buffer_days) -> Booking:
    """Одна спроба: бронювання й подія «створено» в одній транзакції."""
    with transaction.atomic():
        booking = Booking.objects.create(
            unit=unit,
            client=client,
            start_date=start,
            end_date=end,
            status=Booking.Status.CONFIRMED,
            price_per_day=price_per_day,
            total_price=total,
            buffer_days=buffer_days,
        )
        BookingEvent.objects.create(booking=booking, kind=BookingEvent.Kind.CREATED, actor=client)
    return booking


def check_transition(booking: Booking, new_status: str, actor, today: date | None = None) -> None:
    """Перевіряє, чи може actor перевести бронювання в new_status. Інакше — BookingError.

    Одна функція для сервера й інтерфейсу: за нею ж визначається,
    які кнопки показувати (allowed_transitions).
    """
    today = today or date.today()
    allowed = TRANSITIONS.get(booking.status, {})
    if new_status not in allowed:
        raise BookingError(
            f"Перехід «{booking.get_status_display()}» → «{Booking.Status(new_status).label}» недопустимий."
        )

    who = allowed[new_status]
    is_manager = getattr(actor, "is_manager", False)
    if who == "manager" and not is_manager:
        raise BookingError("Цю дію може виконати лише менеджер.")
    if who == "owner_or_manager" and not (is_manager or booking.client_id == actor.pk):
        raise BookingError("Можна скасувати лише власне бронювання.")
    if new_status == Booking.Status.ISSUED:
        if booking.start_date > today:
            raise BookingError(
                f"Видати можна не раніше дати початку оренди ({booking.start_date:%d.%m.%Y})."
            )
        # Фізично екземпляр один: поки попередню оренду не повернули, видати його не можна.
        previous = unreturned_booking(booking)
        if previous is not None:
            raise BookingError(
                f"Екземпляр ще не повернули після заявки № {previous.pk} "
                f"(мали повернути {previous.end_date:%d.%m.%Y})."
            )


def unreturned_booking(booking: Booking) -> Booking | None:
    """Інше бронювання того самого екземпляра, за яким обладнання видано й не повернуто."""
    return (
        Booking.objects.filter(unit_id=booking.unit_id, status=Booking.Status.ISSUED)
        .exclude(pk=booking.pk)
        .first()
    )


def allowed_transitions(booking: Booking, actor, today: date | None = None) -> set[str]:
    """Статуси, у які actor може перевести бронювання зараз (для показу кнопок)."""
    result = set()
    for status in TRANSITIONS.get(booking.status, {}):
        try:
            check_transition(booking, status, actor, today)
        except BookingError:
            continue
        result.add(status)
    return result


def change_status(
    booking: Booking, new_status: str, *, actor, comment: str = "", today: date | None = None
) -> Booking:
    """Переводить бронювання в новий статус з перевіркою прав і журналом.

    Рядок блокується (SELECT ... FOR UPDATE), а перевірка повторюється вже
    під блокуванням. Тому якщо два менеджери одночасно натиснуть «Видати»,
    друга дія побачить новий статус і отримає зрозумілу помилку.
    """
    comment = comment.strip()
    # Клієнт має знати, чому менеджер скасував його бронювання.
    if new_status == Booking.Status.CANCELLED and booking.client_id != actor.pk and not comment:
        raise BookingError("Вкажіть причину скасування — її побачить клієнт.")

    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        check_transition(locked, new_status, actor, today)
        locked.status = new_status
        fields = ["status", "updated_at"]
        if new_status == Booking.Status.RETURNED:
            locked.returned_on = today or date.today()
            locked.late_days, locked.late_fee = calculate_late_fee(
                locked.price_per_day, locked.end_date, locked.returned_on
            )
            fields += ["returned_on", "late_days", "late_fee"]
            if locked.late_days:
                late_note = f"Запізнення {locked.late_days} дн., доплата {locked.late_fee} грн."
                comment = f"{comment} {late_note}".strip()
        locked.save(update_fields=fields)
        BookingEvent.objects.create(booking=locked, kind=new_status, actor=actor, comment=comment)

    for field in fields:
        setattr(booking, field, getattr(locked, field))
    return booking


def calculate_late_fee(price_per_day: Decimal, end: date, returned_on: date) -> tuple[int, Decimal]:
    """Діб запізнення та доплата за них.

    Повернення в день end_date або раніше — без доплати. Кожна доба після
    end_date оплачується за ціною із заявки з коефіцієнтом LATE_FEE_MULTIPLIER.
    Дострокове повернення не зменшує вартість оренди.
    """
    late_days = max(0, (returned_on - end).days)
    fee = (price_per_day * LATE_FEE_MULTIPLIER * late_days).quantize(Decimal("0.01"))
    return late_days, fee


def check_extension(booking: Booking, new_end: date | None, actor, today: date | None = None) -> None:
    """Правила продовження оренди. Інакше — BookingError.

    new_end=None перевіряє лише, чи можна продовжувати взагалі (для показу кнопки).
    """
    today = today or date.today()
    if not (getattr(actor, "is_manager", False) or booking.client_id == actor.pk):
        raise BookingError("Можна продовжити лише власне бронювання.")
    if booking.status not in Booking.ACTIVE_STATUSES:
        raise BookingError("Продовжити можна лише підтверджене або видане бронювання.")
    if today > booking.end_date:
        raise BookingError(
            "Термін оренди вже минув, продовжити не можна. Поверніть обладнання — "
            "за прострочені доби нараховується доплата."
        )
    if new_end is not None and new_end <= booking.end_date:
        raise BookingError(
            f"Нова дата повернення має бути пізніше за поточну ({booking.end_date:%d.%m.%Y})."
        )


def can_extend(booking: Booking, actor, today: date | None = None) -> bool:
    try:
        check_extension(booking, None, actor, today)
    except BookingError:
        return False
    return True


def extend_booking(booking: Booking, new_end: date, *, actor, today: date | None = None) -> Booking:
    """Продовжує оренду до new_end.

    Нова дата перевіряється на зайнятість тим самим обмеженням
    booking_no_overlap_per_unit, що й нове бронювання (з урахуванням
    технічної перерви). Доплата рахується за ціною доби, зафіксованою в заявці.
    """
    for attempt in range(1, CREATE_ATTEMPTS + 1):
        try:
            return _extend_once(booking, new_end, actor, today)
        except OperationalError as exc:
            if not is_deadlock(exc) or attempt == CREATE_ATTEMPTS:
                raise
        except IntegrityError as exc:
            if "booking_no_overlap_per_unit" in str(exc):
                raise BookingConflict(
                    f"Продовжити до {new_end:%d.%m.%Y} неможливо: екземпляр уже заброньовано "
                    "іншим клієнтом на частину цього періоду (з урахуванням технічної перерви)."
                ) from exc
            raise


def _extend_once(booking: Booking, new_end: date, actor, today: date | None) -> Booking:
    with transaction.atomic():
        locked = Booking.objects.select_for_update().get(pk=booking.pk)
        check_extension(locked, new_end, actor, today)
        old_end, old_total = locked.end_date, locked.total_price
        locked.end_date = new_end
        locked.total_price = calculate_price(locked.price_per_day, locked.start_date, new_end)
        locked.save(update_fields=["end_date", "total_price", "updated_at"])
        BookingEvent.objects.create(
            booking=locked,
            kind=BookingEvent.Kind.EXTENDED,
            actor=actor,
            comment=(
                f"Дата повернення {old_end:%d.%m.%Y} → {new_end:%d.%m.%Y}, "
                f"+{(new_end - old_end).days} дн., доплата {locked.total_price - old_total} грн."
            ),
        )
    booking.end_date, booking.total_price = locked.end_date, locked.total_price
    booking.updated_at = locked.updated_at
    return booking
