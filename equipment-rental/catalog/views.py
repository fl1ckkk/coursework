from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from bookings.models import Booking

from .models import EquipmentType, EquipmentUnit


def equipment_list(request):
    """Каталог: пошук за назвою/описом і фільтр за категорією."""
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    items = EquipmentType.objects.filter(is_active=True)
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
    """Картка типу обладнання: екземпляри та їхні зайняті періоди."""
    item = get_object_or_404(EquipmentType, pk=pk, is_active=True)
    units = item.units.filter(status=EquipmentUnit.Status.AVAILABLE).prefetch_related("bookings")
    for unit in units:
        unit.busy_periods = sorted(
            (b for b in unit.bookings.all() if b.status in Booking.ACTIVE_STATUSES),
            key=lambda b: b.start_date,
        )
    return render(request, "catalog/detail.html", {"item": item, "units": units})
