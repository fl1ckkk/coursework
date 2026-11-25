"""Тести каталогу й демонстраційних даних."""

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from bookings.models import Booking

from .management.commands.seed_demo import CLIENTS, EQUIPMENT
from .models import EquipmentType, EquipmentUnit

OVERLAPS_SQL = """
    SELECT count(*) FROM bookings_booking a
    JOIN bookings_booking b
      ON a.unit_id = b.unit_id AND a.id < b.id
     AND daterange(a.start_date, a.end_date + a.buffer_days, '[)')
      && daterange(b.start_date, b.end_date + b.buffer_days, '[)')
    WHERE a.status IN ('confirmed', 'issued') AND b.status IN ('confirmed', 'issued')
"""


class SeedDemoTests(TestCase):
    def seed(self):
        call_command("seed_demo", verbosity=0, stdout=_Null())

    def test_creates_catalog_clients_and_consistent_bookings(self):
        self.seed()
        self.assertEqual(EquipmentType.objects.count(), len(EQUIPMENT))
        self.assertEqual(EquipmentUnit.objects.count(), sum(row[4] for row in EQUIPMENT))
        self.assertEqual(User.objects.filter(role=User.Role.CLIENT).count(), len(CLIENTS))
        self.assertTrue(User.objects.get(username="manager").is_manager)

        statuses = set(Booking.objects.values_list("status", flat=True))
        self.assertEqual(statuses, {"confirmed", "issued", "returned", "cancelled"})
        self.assertTrue(Booking.objects.filter(late_days__gt=0, late_fee__gt=0).exists())

        with connection.cursor() as cursor:
            cursor.execute(OVERLAPS_SQL)
            self.assertEqual(cursor.fetchone()[0], 0)
        # Жоден екземпляр не виданий двом клієнтам одночасно.
        issued_units = list(Booking.objects.filter(status="issued").values_list("unit_id", flat=True))
        self.assertEqual(len(issued_units), len(set(issued_units)))
        # Частина екземплярів лишається вільною для бронювання.
        self.assertTrue(EquipmentUnit.objects.filter(bookings__isnull=True).exists())

    def test_rerun_does_not_duplicate(self):
        self.seed()
        counts = (EquipmentType.objects.count(), User.objects.count(), Booking.objects.count())
        self.seed()
        self.assertEqual(counts, (EquipmentType.objects.count(), User.objects.count(), Booking.objects.count()))


class CatalogOrderingTests(TestCase):
    def test_catalog_sorted_by_category_then_name(self):
        for name, category in [("Б", "Звук"), ("А", "Туризм"), ("В", "Звук")]:
            EquipmentType.objects.create(name=name, category=category)
        items = self.client.get(reverse("catalog:list")).context["items"]
        self.assertEqual([i.name for i in items], ["Б", "В", "А"])


class _Null:
    def write(self, *_):
        pass

    def flush(self):
        pass
