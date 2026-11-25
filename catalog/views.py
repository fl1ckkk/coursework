from datetime import date

from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, render

from bookings.models import Booking
from bookings.services import current_tariff

from .availability import WEEKDAYS, add_months, build_month
from .models import EquipmentType, EquipmentUnit, Tariff

# Скільки місяців уперед можна гортати календар.
MAX_MONTH_OFFSET = 11


def equipment_list(request):
    """Каталог: пошук за назвою/описом і фільтр за категорією."""
    today = date.today()
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")

    current_price = (
        Tariff.objects.filter(equipment_type=OuterRef("pk"), valid_from__lte=today)
        .order_by("-valid_from")
        .values("price_per_day")[:1]
    )
    # Сортування задано явно: у запитах з агрегацією (Count) Django не застосовує Meta.ordering.
    items = (
        EquipmentType.objects.filter(is_active=True)
        .annotate(
            price=Subquery(current_price),
            units_available=Count("units", filter=Q(units__status=EquipmentUnit.Status.AVAILABLE)),
        )
        .order_by("category", "name")
    )
    if query:
        items = items.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if category:
        items = items.filter(category=category)
    categories = (
        EquipmentType.objects.filter(is_active=True)
        .order_by("category")
        .values_list("category", flat=True)
        .distinct()
    )
    return render(
        request,
        "catalog/list.html",
        {"items": items, "query": query, "category": category, "categories": categories},
    )


def equipment_detail(request, pk):
    """Картка типу обладнання: ціна, календар доступності кожного екземпляра."""
    item = get_object_or_404(EquipmentType, pk=pk, is_active=True)
    today = date.today()

    try:
        offset = min(max(int(request.GET.get("m", 0)), 0), MAX_MONTH_OFFSET)
    except ValueError:
        offset = 0
    first_month = add_months(today.replace(day=1), offset)
    second_month = add_months(first_month, 1)

    units = item.units.filter(status=EquipmentUnit.Status.AVAILABLE).prefetch_related("bookings")
    for unit in units:
        active = [b for b in unit.bookings.all() if b.status in Booking.ACTIVE_STATUSES]
        # Минулі бронювання клієнту не цікаві — у списку лише ті, що ще не завершились.
        unit.busy_periods = sorted(
            (b for b in active if b.busy_until > today), key=lambda b: b.start_date
        )
        unit.months = [
            build_month(m.year, m.month, active, today) for m in (first_month, second_month)
        ]

    context = {
        "item": item,
        "units": units,
        "tariff": current_tariff(item, today),
        "weekdays": WEEKDAYS,
        "offset": offset,
        "prev_offset": offset - 1 if offset > 0 else None,
        "next_offset": offset + 1 if offset < MAX_MONTH_OFFSET else None,
    }
    return render(request, "catalog/detail.html", context)
