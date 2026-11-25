"""Тести бізнес-правил бронювання.

Запуск: python manage.py test
Django створює окрему тестову базу, тому робочі дані не змінюються.
"""

import threading
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase

from accounts.models import User
from catalog.models import EquipmentType, EquipmentUnit, Tariff

from .models import Booking, BookingEvent
from .services import (
    BookingConflict,
    BookingError,
    calculate_price,
    change_status,
    create_booking,
)

TODAY = date.today()


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


def make_fixture():
    etype = EquipmentType.objects.create(name="Камера", category="Фото")
    Tariff.objects.create(equipment_type=etype, price_per_day=Decimal("500.00"), valid_from=d(-10))
    unit1 = EquipmentUnit.objects.create(equipment_type=etype, inventory_number="U-1")
    unit2 = EquipmentUnit.objects.create(equipment_type=etype, inventory_number="U-2")
    client = User.objects.create_user("client", password="x", role=User.Role.CLIENT)
    other = User.objects.create_user("other", password="x", role=User.Role.CLIENT)
    manager = User.objects.create_user("manager", password="x", role=User.Role.MANAGER)
    return etype, unit1, unit2, client, other, manager


class PriceTests(TestCase):
    def test_price_is_days_times_daily_rate(self):
        self.assertEqual(calculate_price(Decimal("500.00"), d(1), d(4)), Decimal("1500.00"))

    def test_zero_length_period_rejected(self):
        with self.assertRaises(BookingError):
            calculate_price(Decimal("500.00"), d(1), d(1))


class CreateBookingTests(TestCase):
    def setUp(self):
        self.etype, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture()

    def test_booking_created_with_price_snapshot_and_event(self):
        booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        self.assertEqual(booking.total_price, Decimal("1000.00"))
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertTrue(booking.events.filter(kind=BookingEvent.Kind.CREATED).exists())

    def test_overlapping_booking_same_unit_rejected(self):
        create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(5))
        with self.assertRaises(BookingConflict):
            create_booking(client=self.other, unit=self.unit1, start=d(4), end=d(7))
        self.assertEqual(Booking.objects.count(), 1)  # частково записаної заявки немає

    def test_adjacent_periods_allowed(self):
        """[1;3) і [3;5) не перетинаються: день повернення вільний для наступного клієнта."""
        create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        create_booking(client=self.other, unit=self.unit1, start=d(3), end=d(5))
        self.assertEqual(Booking.objects.count(), 2)

    def test_same_period_other_unit_allowed(self):
        create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(5))
        create_booking(client=self.other, unit=self.unit2, start=d(1), end=d(5))
        self.assertEqual(Booking.objects.count(), 2)

    def test_cancelled_booking_frees_period(self):
        first = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(5))
        change_status(first, Booking.Status.CANCELLED, actor=self.client_user)
        create_booking(client=self.other, unit=self.unit1, start=d(2), end=d(4))
        self.assertEqual(Booking.objects.filter(status=Booking.Status.PENDING).count(), 1)

    def test_past_date_rejected(self):
        with self.assertRaises(BookingError):
            create_booking(client=self.client_user, unit=self.unit1, start=d(-1), end=d(2))

    def test_unit_in_maintenance_rejected(self):
        self.unit1.status = EquipmentUnit.Status.MAINTENANCE
        self.unit1.save()
        with self.assertRaises(BookingError):
            create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(2))

    def test_new_tariff_does_not_change_existing_booking(self):
        booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        Tariff.objects.create(equipment_type=self.etype, price_per_day=Decimal("800.00"), valid_from=d(-1))
        booking.refresh_from_db()
        self.assertEqual(booking.total_price, Decimal("1000.00"))

    def test_database_rejects_overlap_even_without_service(self):
        """Правило діє на рівні СКБД, навіть якщо обійти services.py."""
        Booking.objects.create(unit=self.unit1, client=self.client_user, start_date=d(1),
                               end_date=d(5), price_per_day=1, total_price=4)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(unit=self.unit1, client=self.other, start_date=d(2),
                                   end_date=d(3), price_per_day=1, total_price=1)


class StatusTransitionTests(TestCase):
    def setUp(self):
        _, self.unit1, _, self.client_user, self.other, self.manager = make_fixture()
        self.booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))

    def test_client_cannot_confirm(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.CONFIRMED, actor=self.client_user)

    def test_other_client_cannot_cancel(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.CANCELLED, actor=self.other)

    def test_reject_requires_reason(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.REJECTED, actor=self.manager)

    def test_full_lifecycle(self):
        for status in (Booking.Status.CONFIRMED, Booking.Status.ISSUED, Booking.Status.RETURNED):
            change_status(self.booking, status, actor=self.manager)
        self.assertEqual(self.booking.events.count(), 4)

    def test_cannot_skip_issue(self):
        change_status(self.booking, Booking.Status.CONFIRMED, actor=self.manager)
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.RETURNED, actor=self.manager)


class ConcurrentBookingTests(TransactionTestCase):
    """Два одночасні запити на той самий екземпляр: успішним має бути рівно один."""

    def test_only_one_of_two_parallel_requests_succeeds(self):
        _, unit1, _, client, other, _ = make_fixture()
        barrier = threading.Barrier(2)
        results = []

        def attempt(user):
            try:
                barrier.wait()
                create_booking(client=user, unit=unit1, start=d(1), end=d(4))
                results.append("ok")
            except BookingConflict:
                results.append("conflict")
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(u,)) for u in (client, other)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), ["conflict", "ok"])
        self.assertEqual(Booking.objects.count(), 1)
