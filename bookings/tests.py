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
    allowed_transitions,
    calculate_late_fee,
    extend_booking,
    calculate_price,
    change_status,
    create_booking,
)

TODAY = date.today()


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


def make_fixture(turnaround_days=0):
    # Більшість тестів перевіряє правила без технічної перерви; для перерви — TurnaroundTests.
    etype = EquipmentType.objects.create(
        name="Камера", category="Фото", turnaround_days=turnaround_days
    )
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
        # Ручного погодження немає: коректна заявка одразу підтверджена.
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertTrue(booking.events.filter(kind=BookingEvent.Kind.CREATED).exists())

    def test_overlapping_booking_same_unit_rejected(self):
        create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(5))
        with self.assertRaises(BookingConflict):
            create_booking(client=self.other, unit=self.unit1, start=d(4), end=d(7))
        self.assertEqual(Booking.objects.count(), 1)  # частково записаної заявки немає

    def test_adjacent_periods_allowed(self):
        """Без технічної перерви [1;3) і [3;5) не перетинаються: день повернення вільний."""
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
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 1)

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

    def test_client_cannot_issue(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.ISSUED, actor=self.client_user, today=d(1))

    def test_other_client_cannot_cancel(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.CANCELLED, actor=self.other)

    def test_owner_cancels_without_reason(self):
        change_status(self.booking, Booking.Status.CANCELLED, actor=self.client_user)
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)

    def test_manager_cancel_requires_reason(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.CANCELLED, actor=self.manager, comment="  ")
        change_status(self.booking, Booking.Status.CANCELLED, actor=self.manager, comment="Ремонт")
        self.assertEqual(self.booking.events.last().comment, "Ремонт")

    def test_cannot_issue_before_start_date(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(0))
        change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(1))

    def test_full_lifecycle(self):
        change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        change_status(self.booking, Booking.Status.RETURNED, actor=self.manager)
        kinds = list(self.booking.events.values_list("kind", flat=True))
        self.assertEqual(kinds, ["created", "issued", "returned"])

    def test_cannot_skip_issue(self):
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.RETURNED, actor=self.manager)

    def test_cannot_cancel_after_return(self):
        change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        change_status(self.booking, Booking.Status.RETURNED, actor=self.manager)
        with self.assertRaises(BookingError):
            change_status(self.booking, Booking.Status.CANCELLED, actor=self.manager, comment="x")

    def test_stale_object_cannot_repeat_action(self):
        """Друга дія над застарілою копією (як два менеджери одночасно) відхиляється."""
        stale = Booking.objects.get(pk=self.booking.pk)
        change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        with self.assertRaises(BookingError):
            change_status(stale, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        self.assertEqual(self.booking.events.filter(kind="issued").count(), 1)

    def test_allowed_transitions(self):
        self.assertEqual(allowed_transitions(self.booking, self.client_user), {"cancelled"})
        self.assertEqual(allowed_transitions(self.booking, self.other), set())
        self.assertEqual(
            allowed_transitions(self.booking, self.manager, today=d(1)), {"issued", "cancelled"}
        )
        self.assertEqual(allowed_transitions(self.booking, self.manager, today=d(0)), {"cancelled"})


class ConstraintConsistencyTests(TestCase):
    def test_constraint_condition_matches_active_statuses(self):
        """Умова обмеження в БД і ACTIVE_STATUSES у коді не повинні розійтися."""
        constraint = next(
            c for c in Booking._meta.constraints if c.name == "booking_no_overlap_per_unit"
        )
        self.assertEqual(
            set(dict(constraint.condition.children)["status__in"]),
            {str(s) for s in Booking.ACTIVE_STATUSES},
        )


class ConcurrentBookingTests(TransactionTestCase):
    """Одночасні запити на той самий екземпляр і період: успішним має бути рівно один.

    Повторюємо кілька раундів: взаємне блокування (deadlock) у PostgreSQL
    трапляється не щоразу, і один раунд міг би його не зачепити.
    """

    ROUNDS = 20

    def test_only_one_of_two_parallel_requests_succeeds(self):
        _, unit1, _, client, other, _ = make_fixture()

        for round_no in range(self.ROUNDS):
            start = d(1 + round_no * 5)
            barrier = threading.Barrier(2)
            results = []

            def attempt(user):
                try:
                    barrier.wait()
                    create_booking(client=user, unit=unit1, start=start, end=start + timedelta(days=3))
                    results.append("ok")
                except BookingConflict:
                    results.append("conflict")
                except Exception as exc:  # будь-яка інша помилка — це провал тесту, а не тиша
                    results.append(f"error: {exc!r}")
                finally:
                    connection.close()

            threads = [threading.Thread(target=attempt, args=(u,)) for u in (client, other)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(sorted(results), ["conflict", "ok"], f"раунд {round_no + 1}")

        self.assertEqual(Booking.objects.count(), self.ROUNDS)


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
        self.assertContains(response, "500,00 грн")

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
        self.assertEqual(self.foreign.status, Booking.Status.CONFIRMED)

    def test_cancel_requires_post(self):
        self.client.force_login(self.client_user)
        url = reverse("bookings:cancel", args=[self.mine.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_cannot_cancel_after_issue(self):
        change_status(self.mine, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        self.client.force_login(self.client_user)
        response = self.cancel(self.mine, next=reverse("bookings:detail", args=[self.mine.pk]))
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, Booking.Status.ISSUED)
        self.assertContains(self.client.get(response.url), "недопустимий")

    def test_cancel_button_hidden_after_issue(self):
        change_status(self.mine, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        self.client.force_login(self.client_user)
        response = self.client.get(reverse("bookings:detail", args=[self.mine.pk]))
        self.assertNotContains(response, "bookings/%d/cancel/" % self.mine.pk)

    def test_external_next_ignored(self):
        self.client.force_login(self.client_user)
        response = self.cancel(self.mine, next="https://evil.example.com/")
        self.assertRedirects(response, self.my_url)


class ManagerPanelTests(TestCase):
    """Панель менеджера: доступ, вкладки, пошук, фільтри та дії."""

    def setUp(self):
        _, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture()
        self.client_user.first_name = "Іван"
        self.client_user.save()
        self.today_booking = create_booking(client=self.client_user, unit=self.unit1, start=d(0), end=d(2))
        self.future_booking = create_booking(client=self.other, unit=self.unit2, start=d(5), end=d(7))
        self.list_url = reverse("manage:list")
        self.client.force_login(self.manager)

    def action(self, booking, name, **data):
        return self.client.post(reverse("manage:action", args=[booking.pk, name]), data)

    def make_issued(self, start, end):
        """Видане бронювання з довільними (зокрема минулими) датами — в обхід перевірок форми."""
        booking = Booking.objects.create(
            unit=self.unit1, client=self.other, start_date=start, end_date=end,
            status=Booking.Status.ISSUED, price_per_day=1, total_price=1,
        )
        return booking

    def test_client_gets_403_and_anonymous_redirected(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.list_url).status_code, 302)

    def test_issue_tab_lists_confirmed_sorted_with_counts(self):
        response = self.client.get(self.list_url)
        self.assertEqual(list(response.context["bookings"]), [self.today_booking, self.future_booking])
        self.assertIn(("issue", "До видачі", 2), response.context["tabs"])
        self.assertContains(response, "видача сьогодні")

    def test_search_by_inventory_and_client_name(self):
        response = self.client.get(self.list_url, {"q": "U-2"})
        self.assertEqual(list(response.context["bookings"]), [self.future_booking])
        response = self.client.get(self.list_url, {"q": "іван"})
        self.assertEqual(list(response.context["bookings"]), [self.today_booking])

    def test_date_filter_uses_overlap(self):
        # [d4; d5]: перетинається лише з [d5; d7)
        response = self.client.get(self.list_url, {"from": d(4).isoformat(), "to": d(5).isoformat()})
        self.assertEqual(list(response.context["bookings"]), [self.future_booking])
        # Некоректна дата ігнорується, а не ламає сторінку.
        self.assertEqual(self.client.get(self.list_url, {"from": "abc"}).status_code, 200)

    def test_issue_and_return(self):
        self.assertRedirects(self.action(self.today_booking, "issue"), self.list_url)
        self.today_booking.refresh_from_db()
        self.assertEqual(self.today_booking.status, Booking.Status.ISSUED)
        self.action(self.today_booking, "return")
        self.today_booking.refresh_from_db()
        self.assertEqual(self.today_booking.status, Booking.Status.RETURNED)

    def test_issue_before_start_shows_error(self):
        response = self.action(self.future_booking, "issue")
        self.future_booking.refresh_from_db()
        self.assertEqual(self.future_booking.status, Booking.Status.CONFIRMED)
        self.assertContains(self.client.get(response.url), "не раніше дати початку")

    def test_issue_button_only_when_allowed(self):
        response = self.client.get(self.list_url)
        self.assertContains(response, reverse("manage:action", args=[self.today_booking.pk, "issue"]))
        self.assertNotContains(response, reverse("manage:action", args=[self.future_booking.pk, "issue"]))

    def test_cancel_requires_reason_and_client_sees_it(self):
        self.action(self.future_booking, "cancel", comment="")
        self.future_booking.refresh_from_db()
        self.assertEqual(self.future_booking.status, Booking.Status.CONFIRMED)

        self.action(self.future_booking, "cancel", comment="Екземпляр на ремонті")
        self.future_booking.refresh_from_db()
        self.assertEqual(self.future_booking.status, Booking.Status.CANCELLED)

        self.client.force_login(self.other)
        detail = self.client.get(reverse("bookings:detail", args=[self.future_booking.pk]))
        self.assertContains(detail, "Екземпляр на ремонті")

    def test_overdue_flag(self):
        overdue = self.make_issued(d(-10), d(-3))
        response = self.client.get(self.list_url, {"tab": "issued"})
        self.assertEqual(list(response.context["bookings"]), [overdue])
        self.assertContains(response, "прострочено")

    def test_get_not_allowed_and_unknown_action_404(self):
        url = reverse("manage:action", args=[self.today_booking.pk, "issue"])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.action(self.today_booking, "delete").status_code, 404)

    def test_client_cannot_use_manager_actions(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.action(self.today_booking, "issue").status_code, 403)
        self.today_booking.refresh_from_db()
        self.assertEqual(self.today_booking.status, Booking.Status.CONFIRMED)


class TurnaroundTests(TestCase):
    """Технічна перерва між орендами (поле turnaround_days типу обладнання)."""

    def setUp(self):
        self.etype, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture(
            turnaround_days=1
        )
        self.first = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))

    def test_buffer_copied_into_booking(self):
        self.assertEqual(self.first.buffer_days, 1)
        self.assertEqual(self.first.busy_until, d(4))

    def test_next_rental_cannot_start_on_return_day(self):
        with self.assertRaises(BookingConflict) as ctx:
            create_booking(client=self.other, unit=self.unit1, start=d(3), end=d(5))
        self.assertIn("технічна перерва", str(ctx.exception))

    def test_next_rental_allowed_after_buffer(self):
        create_booking(client=self.other, unit=self.unit1, start=d(4), end=d(6))
        self.assertEqual(Booking.objects.count(), 2)

    def test_earlier_rental_buffer_blocks_too(self):
        """Перерва йде після кожної оренди: попередня оренда теж не може закінчитися впритул."""
        later = create_booking(client=self.other, unit=self.unit1, start=d(10), end=d(12))
        with self.assertRaises(BookingConflict):
            create_booking(client=self.other, unit=self.unit1, start=d(8), end=d(10))
        create_booking(client=self.other, unit=self.unit1, start=d(7), end=d(9))
        self.assertTrue(Booking.objects.filter(pk=later.pk).exists())

    def test_other_unit_not_affected(self):
        create_booking(client=self.other, unit=self.unit2, start=d(3), end=d(5))

    def test_cancelled_booking_frees_buffer(self):
        change_status(self.first, Booking.Status.CANCELLED, actor=self.client_user)
        create_booking(client=self.other, unit=self.unit1, start=d(3), end=d(5))

    def test_changing_type_setting_keeps_existing_bookings(self):
        """Знімок: збільшення перерви не робить недійсними вже створені бронювання."""
        create_booking(client=self.other, unit=self.unit1, start=d(4), end=d(6))
        self.etype.turnaround_days = 5
        self.etype.save()
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 2)
        # Нові бронювання вже з новою перервою.
        new = create_booking(client=self.other, unit=self.unit2, start=d(1), end=d(2))
        self.assertEqual(new.buffer_days, 5)

    def test_database_enforces_buffer(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(unit=self.unit1, client=self.other, start_date=d(3),
                                   end_date=d(4), price_per_day=1, total_price=1)

    def test_detail_page_shows_free_from_date(self):
        response = self.client.get(reverse("catalog:detail", args=[self.etype.pk]))
        self.assertContains(response, "вільний з " + d(4).strftime("%d.%m.%Y"))
        self.assertContains(response, "1 дн. на технічному обслуговуванні")


class ExtensionTests(TestCase):
    """Продовження оренди: права, строки, перевірка зайнятості, доплата."""

    def setUp(self):
        _, self.unit1, self.unit2, self.client_user, self.other, self.manager = make_fixture()
        self.booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))

    def test_owner_extends_and_price_recalculated(self):
        extend_booking(self.booking, d(5), actor=self.client_user)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.end_date, d(5))
        self.assertEqual(self.booking.total_price, Decimal("2000.00"))  # 4 доби × 500
        event = self.booking.events.get(kind=BookingEvent.Kind.EXTENDED)
        self.assertIn("+2 дн.", event.comment)
        self.assertIn("доплата 1000.00 грн", event.comment)

    def test_price_uses_snapshot_not_new_tariff(self):
        Tariff.objects.create(equipment_type=self.unit1.equipment_type, price_per_day=900, valid_from=d(-1))
        extend_booking(self.booking, d(4), actor=self.client_user)
        self.assertEqual(self.booking.total_price, Decimal("1500.00"))  # 3 × 500, а не × 900

    def test_manager_can_extend_issued(self):
        change_status(self.booking, Booking.Status.ISSUED, actor=self.manager, today=d(1))
        extend_booking(self.booking, d(6), actor=self.manager, today=d(2))
        self.assertEqual(self.booking.end_date, d(6))

    def test_other_client_cannot_extend(self):
        with self.assertRaises(BookingError):
            extend_booking(self.booking, d(5), actor=self.other)

    def test_new_end_must_be_later(self):
        for new_end in (d(3), d(2)):
            with self.assertRaises(BookingError):
                extend_booking(self.booking, new_end, actor=self.client_user)

    def test_cannot_extend_after_end_date(self):
        with self.assertRaises(BookingError):
            extend_booking(self.booking, d(6), actor=self.manager, today=d(4))

    def test_cannot_extend_cancelled(self):
        change_status(self.booking, Booking.Status.CANCELLED, actor=self.client_user)
        with self.assertRaises(BookingError):
            extend_booking(self.booking, d(5), actor=self.client_user)

    def test_extension_conflict_with_next_booking(self):
        """Часткове накладання продовження на чуже бронювання відхиляється, дані не змінюються."""
        create_booking(client=self.other, unit=self.unit1, start=d(5), end=d(7))
        with self.assertRaises(BookingConflict):
            extend_booking(self.booking, d(6), actor=self.client_user)
        self.booking.refresh_from_db()
        self.assertEqual((self.booking.end_date, self.booking.total_price), (d(3), Decimal("1000.00")))
        self.assertFalse(self.booking.events.filter(kind="extended").exists())
        # Впритул до наступного бронювання (без технічної перерви) — можна.
        extend_booking(self.booking, d(5), actor=self.client_user)

    def test_extend_view(self):
        self.client.force_login(self.client_user)
        url = reverse("bookings:extend", args=[self.booking.pk])
        response = self.client.post(url, {"new_end": d(4).isoformat()})
        self.assertRedirects(response, reverse("bookings:detail", args=[self.booking.pk]))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.end_date, d(4))
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {"new_end": d(9).isoformat()}).status_code, 403)

    def test_extend_view_shows_error(self):
        self.client.force_login(self.client_user)
        url = reverse("bookings:extend", args=[self.booking.pk])
        response = self.client.post(url, {"new_end": "not-a-date"}, follow=True)
        self.assertContains(response, "Вкажіть нову дату повернення")
        response = self.client.post(url, {"new_end": d(2).isoformat()}, follow=True)
        self.assertContains(response, "має бути пізніше")


class LateReturnTests(TestCase):
    """Повернення із запізненням і заборона видати неповернений екземпляр."""

    def setUp(self):
        _, self.unit1, _, self.client_user, self.other, self.manager = make_fixture()
        self.first = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        self.next = create_booking(client=self.other, unit=self.unit1, start=d(5), end=d(7))
        change_status(self.first, Booking.Status.ISSUED, actor=self.manager, today=d(1))

    def test_late_fee_formula(self):
        self.assertEqual(calculate_late_fee(Decimal("500.00"), d(3), d(3)), (0, Decimal("0.00")))
        self.assertEqual(calculate_late_fee(Decimal("500.00"), d(3), d(1)), (0, Decimal("0.00")))
        self.assertEqual(calculate_late_fee(Decimal("500.00"), d(3), d(5)), (2, Decimal("1500.00")))

    def test_on_time_return(self):
        change_status(self.first, Booking.Status.RETURNED, actor=self.manager, today=d(3))
        self.first.refresh_from_db()
        self.assertEqual((self.first.returned_on, self.first.late_days, self.first.late_fee), (d(3), 0, 0))
        self.assertEqual(self.first.amount_due, Decimal("1000.00"))

    def test_late_return_charges_fee(self):
        change_status(self.first, Booking.Status.RETURNED, actor=self.manager, today=d(6))
        self.first.refresh_from_db()
        self.assertEqual(self.first.late_days, 3)
        self.assertEqual(self.first.late_fee, Decimal("2250.00"))  # 3 × 500 × 1,5
        self.assertEqual(self.first.amount_due, Decimal("3250.00"))
        self.assertIn("Запізнення 3 дн.", self.first.events.last().comment)

    def test_cannot_issue_unit_that_was_not_returned(self):
        with self.assertRaises(BookingError) as ctx:
            change_status(self.next, Booking.Status.ISSUED, actor=self.manager, today=d(5))
        self.assertIn(f"№ {self.first.pk}", str(ctx.exception))
        self.assertNotIn("issued", allowed_transitions(self.next, self.manager, today=d(5)))

        change_status(self.first, Booking.Status.RETURNED, actor=self.manager, today=d(5))
        change_status(self.next, Booking.Status.ISSUED, actor=self.manager, today=d(5))
        self.assertEqual(self.next.status, Booking.Status.ISSUED)

    def test_manager_panel_shows_blocking_badge(self):
        # Сценарій «сьогодні»: перша оренда прострочена, наступна мала початися сьогодні.
        Booking.objects.filter(pk=self.first.pk).update(start_date=d(-5), end_date=d(-2))
        Booking.objects.filter(pk=self.next.pk).update(start_date=TODAY, end_date=d(2))
        self.client.force_login(self.manager)
        response = self.client.get(reverse("manage:list"))
        self.assertContains(response, "ще не повернули")
        self.assertNotContains(response, reverse("manage:action", args=[self.next.pk, "issue"]))


class AvailabilityCalendarTests(TestCase):
    """Календар доступності на картці обладнання."""

    def setUp(self):
        from catalog.availability import build_month, day_states  # noqa: F401

        self.etype, self.unit1, _, self.client_user, _, _ = make_fixture(turnaround_days=1)

    def test_day_states(self):
        from catalog.availability import day_states

        booking = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        states = day_states([booking], d(0), d(10))
        self.assertEqual(states, {d(1): "busy", d(2): "busy", d(3): "buffer"})

    def test_busy_wins_over_buffer(self):
        from catalog.availability import day_states

        self.etype.turnaround_days = 0
        self.etype.save()
        first = create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        first.buffer_days = 1  # перерва попередньої оренди збігається з початком наступної
        second = create_booking(client=self.client_user, unit=self.unit1, start=d(3), end=d(4))
        self.assertEqual(day_states([first, second], d(0), d(10))[d(3)], "busy")

    def test_month_grid_marks_past_and_today(self):
        from catalog.availability import build_month

        month = build_month(TODAY.year, TODAY.month, [], TODAY)
        days = [day for week in month.weeks for day in week if day]
        today_cell = next(day for day in days if day.date == TODAY)
        self.assertTrue(today_cell.is_today)
        self.assertEqual(today_cell.state, "free")
        self.assertTrue(all(day.state == "past" for day in days if day.date < TODAY))

    def test_detail_page_renders_calendar_and_handles_bad_month(self):
        create_booking(client=self.client_user, unit=self.unit1, start=d(1), end=d(3))
        url = reverse("catalog:detail", args=[self.etype.pk])
        response = self.client.get(url)
        self.assertContains(response, 'class="calendar"')
        self.assertContains(response, 'class="busy')
        for bad in ("abc", "-5", "999"):
            self.assertEqual(self.client.get(url, {"m": bad}).status_code, 200)


class ManagerPaginationTests(TestCase):
    def test_pagination(self):
        from .manager_views import PAGE_SIZE

        _, unit1, _, client_user, _, manager = make_fixture()
        for i in range(PAGE_SIZE + 5):
            create_booking(client=client_user, unit=unit1, start=d(1 + i * 2), end=d(2 + i * 2))
        self.client.force_login(manager)
        first = self.client.get(reverse("manage:list"))
        self.assertEqual(len(first.context["bookings"]), PAGE_SIZE)
        self.assertContains(first, "Сторінка 1 з 2")
        second = self.client.get(reverse("manage:list"), {"page": 2})
        self.assertEqual(len(second.context["bookings"]), 5)
        self.assertEqual(self.client.get(reverse("manage:list"), {"page": "x"}).status_code, 200)
