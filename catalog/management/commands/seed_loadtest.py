"""Готує базу до навантажувального тестування.

Запуск (після seed_demo, на окремій базі):
    python manage.py seed_loadtest --clients 100

Створює клієнтів loadclient001 … loadclientNNN з паролем LOAD_PASSWORD,
під якими входять віртуальні користувачі Locust (loadtest/locustfile.py).
Повторний запуск безпечний.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User

LOAD_PASSWORD = "load-pass-123"


class Command(BaseCommand):
    help = "Створює клієнтів для навантажувального тестування"

    def add_arguments(self, parser):
        parser.add_argument("--clients", type=int, default=100)

    @transaction.atomic
    def handle(self, *args, clients, **options):
        created = 0
        for n in range(1, clients + 1):
            user, is_new = User.objects.get_or_create(
                username=f"loadclient{n:03d}",
                defaults={"first_name": "Тест", "last_name": f"Навантаження {n}", "role": User.Role.CLIENT},
            )
            if is_new:
                user.set_password(LOAD_PASSWORD)
                user.save()
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Клієнтів для навантаження: {clients} (нових: {created}); пароль: {LOAD_PASSWORD}"
        ))
