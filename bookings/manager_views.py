"""Панель менеджера: видача, прийом повернення та скасування бронювань.

Погодження вручну немає: заявки клієнтів підтверджуються автоматично
(див. services.create_booking). Каталог менеджер веде через адмінку Django.
"""

from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Booking
from .services import BookingError, allowed_transitions, change_status, unreturned_booking

# Вкладки: ключ -> (назва, статуси, сортування).
TABS = {
    "issue": ("До видачі", (Booking.Status.CONFIRMED,), ("start_date", "pk")),
    "issued": ("Видані", (Booking.Status.ISSUED,), ("end_date", "pk")),
    "archive": (
        "Архів",
        (Booking.Status.RETURNED, Booking.Status.CANCELLED),
        ("-updated_at",),
    ),
}

# Заявок на одній сторінці панелі (див. висновки навантажувального тестування).
PAGE_SIZE = 20

# Дія з адреси -> новий статус і повідомлення про успіх.
ACTIONS = {
    "issue": (Booking.Status.ISSUED, "Обладнання за заявкою № {pk} видано."),
    "return": (Booking.Status.RETURNED, "Повернення за заявкою № {pk} прийнято."),
    "cancel": (Booking.Status.CANCELLED, "Заявку № {pk} скасовано."),
}


def manager_required(view):
    """Доступ лише для користувачів із роллю «Менеджер»."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_manager:
            raise PermissionDenied("Сторінка доступна лише менеджеру.")
        return view(request, *args, **kwargs)

    return wrapper


def mark(booking: Booking, user, today: date) -> Booking:
    """Додає до бронювання позначки й доступні дії для шаблону."""
    booking.allowed = allowed_transitions(booking, user, today)
    booking.is_issue_today = booking.status == Booking.Status.CONFIRMED and booking.start_date == today
    booking.is_not_picked_up = booking.status == Booking.Status.CONFIRMED and booking.start_date < today
    # end_date — день повернення: прострочено, якщо він уже минув.
    booking.is_overdue = booking.status == Booking.Status.ISSUED and booking.end_date < today
    # Для заявок, які вже час видавати: чи повернули екземпляр після попередньої оренди.
    booking.blocking = (
        unreturned_booking(booking)
        if booking.status == Booking.Status.CONFIRMED and booking.start_date <= today
        else None
    )
    return booking


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@manager_required
def manage_list(request):
    """Список бронювань із вкладками, пошуком і фільтром за періодом."""
    today = date.today()
    tab = request.GET.get("tab", "issue")
    if tab not in TABS:
        tab = "issue"
    _, statuses, ordering = TABS[tab]

    query = request.GET.get("q", "").strip()
    date_from = parse_date(request.GET.get("from", ""))
    date_to = parse_date(request.GET.get("to", ""))

    bookings = Booking.objects.select_related("unit__equipment_type", "client")
    if query:
        bookings = bookings.filter(
            Q(client__username__icontains=query)
            | Q(client__first_name__icontains=query)
            | Q(client__last_name__icontains=query)
            | Q(unit__inventory_number__icontains=query)
            | Q(unit__equipment_type__name__icontains=query)
        )
    # Період бронювання [start; end) перетинається з вибраним [from; to].
    if date_from:
        bookings = bookings.filter(end_date__gt=date_from)
    if date_to:
        bookings = bookings.filter(start_date__lte=date_to)

    counts = {key: bookings.filter(status__in=st).count() for key, (_, st, _) in TABS.items()}
    page = Paginator(bookings.filter(status__in=statuses).order_by(*ordering), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    rows = [mark(b, request.user, today) for b in page]
    tabs = [(key, label, counts[key]) for key, (label, _, _) in TABS.items()]

    filters = request.GET.copy()
    filters.pop("tab", None)
    filters.pop("page", None)
    page_query = request.GET.copy()
    page_query.pop("page", None)
    return render(
        request,
        "bookings/manage_list.html",
        {
            "bookings": rows,
            "page": page,
            "page_query": page_query.urlencode(),
            "tab": tab,
            "tabs": tabs,
            "query": query,
            "date_from": date_from,
            "date_to": date_to,
            "filters": filters.urlencode(),
        },
    )


@manager_required
@require_POST
def manage_action(request, pk, action):
    """Видача, прийом повернення або скасування. Лише POST."""
    if action not in ACTIONS:
        raise Http404
    new_status, success = ACTIONS[action]
    booking = get_object_or_404(Booking, pk=pk)
    try:
        change_status(booking, new_status, actor=request.user, comment=request.POST.get("comment", ""))
    except BookingError as exc:
        messages.error(request, f"Заявка № {pk}: {exc}")
    else:
        messages.success(request, success.format(pk=pk))

    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("manage:list")
