from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from catalog.models import EquipmentType

from .forms import BookingForm
from .manager_views import mark
from .models import Booking
from .services import (
    BookingError,
    allowed_transitions,
    can_extend,
    extend_booking,
    change_status,
    create_booking,
    current_tariff,
)

# Вкладки сторінки «Мої бронювання»: назва -> статуси.
MY_TABS = {
    "active": ("Поточні", Booking.ACTIVE_STATUSES),
    "archive": ("Архів", (Booking.Status.RETURNED, Booking.Status.CANCELLED)),
}


@login_required
def booking_create(request, type_pk):
    """Оформлення заявки на бронювання (лише для клієнтів).

    GET — порожня форма з цінами; POST — перевірка й створення заявки.
    """
    if request.user.is_manager:
        raise PermissionDenied("Менеджер не оформлює заявки на оренду.")

    equipment_type = get_object_or_404(EquipmentType, pk=type_pk, is_active=True)
    tariff = current_tariff(equipment_type, date.today())

    if request.method == "POST":
        form = BookingForm(request.POST, equipment_type=equipment_type)
        if form.is_valid():
            try:
                booking = create_booking(
                    client=request.user,
                    unit=form.cleaned_data["unit"],
                    start=form.cleaned_data["start_date"],
                    end=form.cleaned_data["end_date"],
                )
            except BookingError as exc:
                # Зайнятий період, відсутній тариф тощо — показуємо над формою.
                form.add_error(None, str(exc))
            else:
                messages.success(request, "Бронювання підтверджено. Заберіть обладнання в день початку оренди.")
                return redirect("bookings:detail", pk=booking.pk)
    else:
        form = BookingForm(equipment_type=equipment_type, initial=_initial_from_query(request))

    return render(
        request,
        "bookings/create.html",
        {"form": form, "item": equipment_type, "tariff": tariff},
    )


@login_required
def my_bookings(request):
    """Список заявок поточного користувача з вкладками «Поточні» та «Архів»."""
    tab = request.GET.get("tab", "active")
    if tab not in MY_TABS:
        tab = "active"
    bookings = (
        Booking.objects.filter(client=request.user, status__in=MY_TABS[tab][1])
        .select_related("unit__equipment_type")
        .order_by("start_date" if tab == "active" else "-start_date")
    )
    for booking in bookings:
        booking.can_cancel = can_cancel(booking, request.user)
    tabs = [(key, label) for key, (label, _) in MY_TABS.items()]
    return render(
        request, "bookings/my_list.html", {"bookings": bookings, "tab": tab, "tabs": tabs}
    )


@login_required
@require_POST
def booking_cancel(request, pk):
    """Скасування заявки власником (або менеджером) до видачі обладнання.

    Лише POST: дія змінює дані, тому її не можна виконати простим переходом за посиланням.
    """
    booking = get_object_or_404(Booking, pk=pk)
    if not (request.user.is_manager or booking.client_id == request.user.pk):
        raise PermissionDenied
    try:
        change_status(booking, Booking.Status.CANCELLED, actor=request.user)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Заявку № {booking.pk} скасовано.")
    # Повертаємо туди, звідки натиснули кнопку, але лише на адресу цього ж сайту.
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("bookings:my")


@login_required
@require_POST
def booking_extend(request, pk):
    """Продовження оренди клієнтом-власником або менеджером. Лише POST."""
    booking = get_object_or_404(Booking, pk=pk)
    if not (request.user.is_manager or booking.client_id == request.user.pk):
        raise PermissionDenied
    try:
        new_end = date.fromisoformat(request.POST.get("new_end", ""))
    except ValueError:
        messages.error(request, "Вкажіть нову дату повернення.")
    else:
        try:
            extend_booking(booking, new_end, actor=request.user)
        except BookingError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Оренду продовжено до {booking.end_date:%d.%m.%Y}. "
                f"Нова вартість: {booking.total_price} грн.",
            )
    return redirect("bookings:detail", pk=pk)


@login_required
def booking_detail(request, pk):
    """Сторінка заявки. Бачить лише її власник або менеджер."""
    booking = get_object_or_404(
        Booking.objects.select_related("unit__equipment_type", "client"), pk=pk
    )
    if not (request.user.is_manager or booking.client_id == request.user.pk):
        raise PermissionDenied
    events = booking.events.select_related("actor")
    context = {
        "booking": booking,
        "events": events,
        "can_extend": can_extend(booking, request.user),
        "extend_min": booking.end_date + timedelta(days=1),
    }
    if request.user.is_manager:
        # Менеджер бачить ті самі кнопки дій, що й у панелі.
        context["booking"] = mark(booking, request.user, date.today())
    else:
        context["can_cancel"] = can_cancel(booking, request.user)
    return render(request, "bookings/detail.html", context)


def can_cancel(booking: Booking, user) -> bool:
    """Чи показувати клієнту кнопку «Скасувати».

    Правила беруться з services.allowed_transitions — тих самих перевірок,
    що й у services.change_status, тому кнопка й сервер не можуть розійтися.
    """
    return Booking.Status.CANCELLED in allowed_transitions(booking, user)


def _initial_from_query(request) -> dict:
    """Дозволяє відкрити форму з уже вибраним екземпляром: ?unit=<id>."""
    unit = request.GET.get("unit")
    return {"unit": unit} if unit and unit.isdigit() else {}
