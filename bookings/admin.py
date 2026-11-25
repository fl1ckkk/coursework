from django.contrib import admin

from .models import Booking, BookingEvent


class EventInline(admin.TabularInline):
    model = BookingEvent
    extra = 0
    readonly_fields = ("kind", "actor", "comment", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Бронювання в адмінці лише для перегляду.

    Створення, продовження, видача, повернення й скасування відбуваються на сайті
    через bookings.services: там перевіряються права й правила, пишеться журнал
    подій і рахується доплата. Пряме редагування в адмінці обійшло б усе це.
    """

    list_display = ("id", "unit", "client", "start_date", "end_date", "status", "total_price", "late_fee")
    list_filter = ("status",)
    search_fields = ("unit__inventory_number", "client__username", "client__last_name")
    date_hierarchy = "start_date"
    inlines = [EventInline]

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
