"""Тести реєстрації клієнта."""

from django.test import TestCase
from django.urls import reverse

from .models import User

VALID = {
    "username": "petro",
    "first_name": "Петро",
    "last_name": "Тестовий",
    "email": "Petro@Example.com",
    "phone": "+38 (050) 123-45-67",
    "password1": "Rental-pass-2026",
    "password2": "Rental-pass-2026",
}


class RegistrationTests(TestCase):
    url = reverse("register")

    def post(self, **changes):
        return self.client.post(self.url, {**VALID, **changes})

    def test_page_opens(self):
        self.assertContains(self.client.get(self.url), "Зареєструватися")

    def test_valid_registration_creates_client_and_logs_in(self):
        response = self.post()
        self.assertRedirects(response, reverse("catalog:list"))
        user = User.objects.get(username="petro")
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertEqual(user.email, "petro@example.com")
        self.assertEqual(user.phone, "+380501234567")
        self.assertFalse(user.is_staff)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_role_cannot_be_injected(self):
        """Навіть якщо підставити role=manager у запит, користувач стає клієнтом."""
        self.post(role="manager", is_staff="on")
        user = User.objects.get(username="petro")
        self.assertEqual(user.role, User.Role.CLIENT)
        self.assertFalse(user.is_staff)

    def test_password_mismatch(self):
        self.post(password2="Other-pass-2026")
        self.assertFalse(User.objects.exists())

    def test_weak_password_rejected(self):
        self.post(password1="12345678", password2="12345678")
        self.assertFalse(User.objects.exists())

    def test_duplicate_username_and_email(self):
        User.objects.create_user("petro", email="other@example.com", password="x")
        self.post()
        self.assertEqual(User.objects.count(), 1)
        self.post(username="petro2", email="OTHER@example.com")
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_phone(self):
        response = self.post(phone="12-34")
        self.assertContains(response, "10–15 цифр")
        self.assertFalse(User.objects.exists())

    def test_authenticated_user_redirected(self):
        user = User.objects.create_user("someone", password="x")
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse("catalog:list"))

    def test_new_client_can_book_after_registration(self):
        """Наскрізний сценарій: реєстрація -> одразу доступна форма бронювання."""
        from catalog.models import EquipmentType

        etype = EquipmentType.objects.create(name="Камера", category="Фото")
        self.post()
        response = self.client.get(reverse("bookings:create", args=[etype.pk]))
        self.assertEqual(response.status_code, 200)
