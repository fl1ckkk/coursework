from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.db import models
from django.db.models import Func, Q

from catalog.models import EquipmentUnit


class DateRange(Func):
    """SQL-функція daterange(start, end, '[)') — напіввідкритий діапазон дат."""

    function = "daterange"
    output_field = DateRangeField()


class Booking(models.Model):
    """Бронювання конкретного екземпляра на період [start_date; end_date).

    Межі інтервалу: start_date — день видачі (входить у період),
    end_date — день повернення (не входить). Тому бронювання
    1–3 і 3–5 числа не перетинаються, а кількість діб = end_date - start_date.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Очікує погодження"
        CONFIRMED = "confirmed", "Погоджено"
        ISSUED = "issued", "Видано"
        RETURNED = "returned", "Повернено"
        REJECTED = "rejected", "Відхилено"
        CANCELLED = "cancelled", "Скасовано"

    # Статуси, у яких бронювання займає екземпляр і блокує інші заявки.
    ACTIVE_STATUSES = (Status.PENDING, Status.CONFIRMED, Status.ISSUED)

    unit = models.ForeignKey(
        EquipmentUnit, on_delete=models.PROTECT, related_name="bookings", verbose_name="екземпляр"
    )
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
        verbose_name="клієнт",
    )
    start_date = models.DateField("дата видачі")
    end_date = models.DateField("дата повернення")
    status = models.CharField(
        "статус", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    # Ціну фіксуємо в момент створення, щоб зміна тарифу не змінила вже оформлену заявку.
    price_per_day = models.DecimalField("ціна за добу на момент бронювання", max_digits=10, decimal_places=2)
    total_price = models.DecimalField("вартість, грн", max_digits=12, decimal_places=2)
    created_at = models.DateTimeField("створено", auto_now_add=True)
    updated_at = models.DateTimeField("змінено", auto_now=True)

    class Meta:
        verbose_name = "бронювання"
        verbose_name_plural = "бронювання"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gt=models.F("start_date")),
                name="booking_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0), name="booking_total_non_negative"
            ),
            # Головне бізнес-правило: активні бронювання одного екземпляра
            # не можуть перетинатися в часі. Перевіряє сама СКБД, тому правило
            # діє навіть для двох одночасних запитів.
            ExclusionConstraint(
                name="booking_no_overlap_per_unit",
                expressions=[
                    ("unit", RangeOperators.EQUAL),
                    (
                        DateRange("start_date", "end_date", models.Value("[)")),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status__in=["pending", "confirmed", "issued"]),
                violation_error_message="Цей екземпляр уже заброньовано на частину вибраного періоду.",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "status"], name="booking_client_status_idx"),
        ]

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days

    def __str__(self) -> str:
        return f"#{self.pk} {self.unit} {self.start_date}–{self.end_date} ({self.get_status_display()})"


class BookingEvent(models.Model):
    """Журнал змін бронювання: хто, коли й що зробив."""

    class Kind(models.TextChoices):
        CREATED = "created", "Створено"
        CONFIRMED = "confirmed", "Погоджено"
        REJECTED = "rejected", "Відхилено"
        CANCELLED = "cancelled", "Скасовано"
        ISSUED = "issued", "Видано"
        RETURNED = "returned", "Повернено"

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="events", verbose_name="бронювання"
    )
    kind = models.CharField("подія", max_length=16, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", verbose_name="виконавець"
    )
    comment = models.CharField("коментар", max_length=255, blank=True)
    created_at = models.DateTimeField("час", auto_now_add=True)

    class Meta:
        verbose_name = "подія бронювання"
        verbose_name_plural = "події бронювань"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.booking_id}"
