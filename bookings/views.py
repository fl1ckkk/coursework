from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from catalog.models import EquipmentType

from .forms import BookingForm
from .models import Booking
from .services import BookingError, create_booking, current_tariff


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
                messages.success(request, "Заявку створено. Очікуйте погодження менеджера.")
                return redirect("bookings:detail", pk=booking.pk)
    else:
        form = BookingForm(equipment_type=equipment_type, initial=_initial_from_query(request))

    return render(
        request,
        "bookings/create.html",
        {"form": form, "item": equipment_type, "tariff": tariff},
    )


@login_required
def booking_detail(request, pk):
    """Сторінка заявки. Бачить лише її власник або менеджер."""
    booking = get_object_or_404(
        Booking.objects.select_related("unit__equipment_type", "client"), pk=pk
    )
    if not (request.user.is_manager or booking.client_id == request.user.pk):
        raise PermissionDenied
    events = booking.events.select_related("actor")
    return render(request, "bookings/detail.html", {"booking": booking, "events": events})


def _initial_from_query(request) -> dict:
    """Дозволяє відкрити форму з уже вибраним екземпляром: ?unit=<id>."""
    unit = request.GET.get("unit")
    return {"unit": unit} if unit and unit.isdigit() else {}
