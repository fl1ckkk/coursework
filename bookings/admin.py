from django.contrib import admin

from .models import Booking, BookingEvent


class EventInline(admin.TabularInline):
    model = BookingEvent
    extra = 0
    readonly_fields = ("kind", "actor", "comment", "created_at")
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "unit", "client", "start_date", "end_date", "status", "total_price")
    list_filter = ("status",)
    search_fields = ("unit__inventory_number", "client__username")
    inlines = [EventInline]
    # Ціну й вартість змінюємо лише через bookings.services, щоб не порушити історію.
    readonly_fields = ("price_per_day", "total_price", "created_at", "updated_at")
