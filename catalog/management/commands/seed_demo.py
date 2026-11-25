"""Заповнює базу синтетичними демонстраційними даними.

Запуск: python manage.py seed_demo
Повторний запуск безпечний: існуючі записи не дублюються.
Усі дані вигадані; паролі — лише для локальної демонстрації.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from catalog.models import EquipmentType, EquipmentUnit, Tariff

DEMO_PASSWORD = "demo-pass-123"

EQUIPMENT = [
    ("Камера Sony A7 III", "Фото й відео", "Повнокадрова бездзеркальна камера.", "900.00", 3),
    ("Об'єктив 24-70 мм f/2.8", "Фото й відео", "Універсальний зум-об'єктив.", "450.00", 2),
    ("Світлодіодна панель 60 Вт", "Світло", "Постійне світло з регулюванням температури.", "300.00", 4),
    ("Намет на 3 особи", "Туризм", "Двошаровий намет, вага 2,8 кг.", "200.00", 5),
    ("Перфоратор 800 Вт", "Інструменти", "SDS-plus, три режими роботи.", "250.00", 2),
]


class Command(BaseCommand):
    help = "Створює демонстраційних користувачів, обладнання й тарифи"

    @transaction.atomic
    def handle(self, *args, **options):
        users = [
            ("manager", "Марія", "Менеджерська", User.Role.MANAGER),
            ("client1", "Іван", "Клієнтенко", User.Role.CLIENT),
            ("client2", "Олена", "Орендаренко", User.Role.CLIENT),
        ]
        for username, first, last, role in users:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last, "role": role}
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()

        start = date.today() - timedelta(days=30)
        for index, (name, category, description, price, count) in enumerate(EQUIPMENT, start=1):
            etype, _ = EquipmentType.objects.get_or_create(
                name=name, defaults={"category": category, "description": description}
            )
            Tariff.objects.get_or_create(
                equipment_type=etype, valid_from=start, defaults={"price_per_day": Decimal(price)}
            )
            for n in range(1, count + 1):
                EquipmentUnit.objects.get_or_create(
                    inventory_number=f"INV-{index:02d}-{n:03d}", defaults={"equipment_type": etype}
                )

        self.stdout.write(self.style.SUCCESS(
            f"Демо-дані готові. Користувачі: manager, client1, client2; пароль: {DEMO_PASSWORD}"
        ))
