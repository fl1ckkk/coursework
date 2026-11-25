"""Тести бізнес-правил бронювання.

Запуск: python manage.py test
Django створює окрему тестову базу, тому робочі дані не змінюються.
"""

import threading
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

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


class BookingViewTests(TestCase):
    """Сторінки оформлення й перегляду заявки."""

    def setUp(self):
        self.etype, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture()
        self.url = reverse("bookings:create", args=[self.etype.pk])

    def post(self, unit, start, end):
        return self.client.post(
            self.url, {"unit": unit.pk, "start_date": start.isoformat(), "end_date": end.isoformat()}
        )

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_manager_cannot_open_form(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_client_sees_form_with_price(self):
        self.client.force_login(self.client_user)
        response = self.client.get(self.url)
        self.assertContains(response, "Надіслати заявку")
        self.assertContains(response, "500,00 грн / доба")

    def test_valid_post_creates_booking_and_redirects(self):
        self.client.force_login(self.client_user)
        response = self.post(self.unit1, d(1), d(3))
        booking = Booking.objects.get()
        self.assertRedirects(response, reverse("bookings:detail", args=[booking.pk]))
        self.assertEqual(booking.client, self.client_user)
        self.assertEqual(booking.total_price, Decimal("1000.00"))

    def test_overlap_shows_error_on_form(self):
        create_booking(client=self.other, unit=self.unit1, start=d(1), end=d(5))
        self.client.force_login(self.client_user)
        response = self.post(self.unit1, d(2), d(4))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже заброньовано")
        self.assertEqual(Booking.objects.count(), 1)

    def test_invalid_dates_show_error(self):
        self.client.force_login(self.client_user)
        response = self.post(self.unit1, d(3), d(1))
        self.assertContains(response, "пізніше за дату видачі")
        self.assertFalse(Booking.objects.exists())

    def test_unit_of_other_type_rejected(self):
        foreign_type = EquipmentType.objects.create(name="Намет", category="Туризм")
        foreign_unit = EquipmentUnit.objects.create(equipment_type=foreign_type, inventory_number="X-1")
        self.client.force_login(self.client_user)
        response = self.post(foreign_unit, d(1), d(2))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Booking.objects.exists())

    def test_detail_visible_to_owner_and_manager_only(self):
        booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        url = reverse("bookings:detail", args=[booking.pk])
        for user, expected in ((self.client_user, 200), (self.manager, 200), (self.other, 403)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, expected, user.username)


class MyBookingsTests(TestCase):
    """Сторінка «Мої бронювання» та скасування заявки."""

    def setUp(self):
        _, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture()
        self.mine = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        self.foreign = create_booking(client=self.other, unit=self.unit2, start=d(1), end=d(3))
        self.my_url = reverse("bookings:my")

    def cancel(self, booking, **extra):
        return self.client.post(reverse("bookings:cancel", args=[booking.pk]), extra)

    def test_list_shows_only_own_bookings(self):
        self.client.force_login(self.client_user)
        response = self.client.get(self.my_url)
        self.assertEqual(list(response.context["bookings"]), [self.mine])

    def test_cancelled_booking_moves_to_archive(self):
        self.client.force_login(self.client_user)
        self.cancel(self.mine)
        self.assertEqual(list(self.client.get(self.my_url).context["bookings"]), [])
        archive = self.client.get(self.my_url, {"tab": "archive"}).context["bookings"]
        self.assertEqual(list(archive), [self.mine])

    def test_owner_can_cancel(self):
        self.client.force_login(self.client_user)
        response = self.cancel(self.mine)
        self.assertRedirects(response, self.my_url)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Booking.Status.CANCELLED)
        self.assertTrue(self.mine.events.filter(kind=BookingEvent.Kind.CANCELLED).exists())

    def test_cannot_cancel_foreign_booking(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.cancel(self.foreign).status_code, 403)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.status, Booking.Status.PENDING)

    def test_cancel_requires_post(self):
        self.client.force_login(self.client_user)
        url = reverse("bookings:cancel", args=[self.mine.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_cannot_cancel_after_issue(self):
        change_status(self.mine, Booking.Status.CONFIRMED, actor=self.manager)
        change_status(self.mine, Booking.Status.ISSUED, actor=self.manager)
        self.client.force_login(self.client_user)
        response = self.cancel(self.mine, next=reverse("bookings:detail", args=[self.mine.pk]))
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Booking.Status.ISSUED)
        self.assertContains(self.client.get(response.url), "недопустимий")

    def test_cancel_button_hidden_after_issue(self):
        change_status(self.mine, Booking.Status.CONFIRMED, actor=self.manager)
        change_status(self.mine, Booking.Status.ISSUED, actor=self.manager)
        self.client.force_login(self.client_user)
        response = self.client.get(reverse("bookings:detail", args=[self.mine.pk]))
        self.assertNotContains(response, "bookings/%d/cancel/" % self.mine.pk)

    def test_external_next_ignored(self):
        self.client.force_login(self.client_user)
        response = self.cancel(self.mine, next="https://evil.example.com/")
        self.assertRedirects(response, self.my_url)
