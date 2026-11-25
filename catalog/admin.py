from django.contrib import admin

from .models import EquipmentType, EquipmentUnit, Tariff


class UnitInline(admin.TabularInline):
    model = EquipmentUnit
    extra = 0


class TariffInline(admin.TabularInline):
    model = Tariff
    extra = 0


@admin.register(EquipmentType)
class EquipmentTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name", "description")
    inlines = [UnitInline, TariffInline]


@admin.register(EquipmentUnit)
class EquipmentUnitAdmin(admin.ModelAdmin):
    list_display = ("inventory_number", "equipment_type", "status")
    list_filter = ("status", "equipment_type__category")
    search_fields = ("inventory_number", "equipment_type__name")
