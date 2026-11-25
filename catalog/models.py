from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class EquipmentType(models.Model):
    """Товарна позиція каталогу, наприклад «Камера Sony A7 III».

    Сама позиція не бронюється: бронюють конкретний екземпляр (EquipmentUnit),
    бо два однакові предмети можуть мати різні графіки доступності.
    """

    name = models.CharField("назва", max_length=200, unique=True)
    category = models.CharField("категорія", max_length=100)
    description = models.TextField("опис", blank=True)
    is_active = models.BooleanField("показувати в каталозі", default=True)
    turnaround_days = models.PositiveSmallIntegerField(
        "технічна перерва, днів",
        default=1,
        validators=[MaxValueValidator(30)],
        help_text="Скільки днів після повернення екземпляр недоступний (перевірка, чистка, зарядка).",
    )

    class Meta:
        verbose_name = "тип обладнання"
        verbose_name_plural = "типи обладнання"
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return self.name


class EquipmentUnit(models.Model):
    """Фізичний екземпляр обладнання з інвентарним номером."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Доступний"
        MAINTENANCE = "maintenance", "На обслуговуванні"
        RETIRED = "retired", "Списаний"

    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.PROTECT, related_name="units", verbose_name="тип"
    )
    inventory_number = models.CharField("інвентарний номер", max_length=50, unique=True)
    status = models.CharField("стан", max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    note = models.CharField("примітка", max_length=255, blank=True)

    class Meta:
        verbose_name = "екземпляр"
        verbose_name_plural = "екземпляри"
        ordering = ["inventory_number"]

    def __str__(self) -> str:
        return f"{self.equipment_type} #{self.inventory_number}"


class Tariff(models.Model):
    """Ціна доби оренди для типу обладнання, чинна з певної дати.

    Історію тарифів зберігаємо: нова ціна — новий запис, а не зміна старого.
    Тоді вже створені бронювання не перераховуються за новим прайсом.
    """

    equipment_type = models.ForeignKey(
        EquipmentType, on_delete=models.CASCADE, related_name="tariffs", verbose_name="тип"
    )
    price_per_day = models.DecimalField(
        "ціна за добу, грн",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    valid_from = models.DateField("чинний з")

    class Meta:
        verbose_name = "тариф"
        verbose_name_plural = "тарифи"
        ordering = ["equipment_type", "-valid_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["equipment_type", "valid_from"], name="tariff_unique_per_type_and_date"
            ),
            models.CheckConstraint(
                condition=Q(price_per_day__gt=0), name="tariff_price_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment_type}: {self.price_per_day} грн/доба з {self.valid_from}"
