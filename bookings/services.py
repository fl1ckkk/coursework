"""Бізнес-логіка бронювань.

Усі зміни бронювань проходять через функції цього модуля, а не напряму
через модель: тут перевіряються права, допустимі переходи статусів
і пишеться журнал подій (BookingEvent).
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from catalog.models import EquipmentUnit, Tariff

from .models import Booking, BookingEvent


class BookingError(Exception):
    """Помилка, яку можна показати користувачеві як є."""


class BookingConflict(BookingError):
    """Екземпляр уже зайнятий на частину періоду."""


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
    """
    validate_period(start, end)
    if unit.status != EquipmentUnit.Status.AVAILABLE:
        raise BookingError("Цей екземпляр зараз недоступний для оренди.")

    tariff = tariff_for(unit, start)
    total = calculate_price(tariff.price_per_day, start, end)

    try:
        with transaction.atomic():
            booking = Booking.objects.create(
                unit=unit,
                client=client,
                start_date=start,
                end_date=end,
                status=Booking.Status.CONFIRMED,
                price_per_day=tariff.price_per_day,
                total_price=total,
            )
            BookingEvent.objects.create(
                booking=booking, kind=BookingEvent.Kind.CREATED, actor=client
            )
    except IntegrityError as exc:
        if "booking_no_overlap_per_unit" in str(exc):
            raise BookingConflict(
                "Цей екземпляр уже заброньовано на частину вибраного періоду."
            ) from exc
        raise
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
    if new_status == Booking.Status.ISSUED and booking.start_date > today:
        raise BookingError(
            f"Видати можна не раніше дати початку оренди ({booking.start_date:%d.%m.%Y})."
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
        locked.save(update_fields=["status", "updated_at"])
        BookingEvent.objects.create(booking=locked, kind=new_status, actor=actor, comment=comment)

    booking.status, booking.updated_at = locked.status, locked.updated_at
    return booking
