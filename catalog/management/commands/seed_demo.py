"""Заповнює базу синтетичними демонстраційними даними.

Запуск: python manage.py seed_demo

Створює:
  * менеджера й 12 клієнтів (пароль для всіх — DEMO_PASSWORD);
  * каталог із ~20 позицій у 7 категоріях, екземпляри й тарифи;
  * сценарні бронювання для демонстрації панелі менеджера (лише в порожній базі);
  * історію бронювань демо-клієнтів: повернені (частина із запізненням),
    скасовані, видані зараз і майбутні.

Повторний запуск безпечний: наявні записи не дублюються, а історія
створюється лише для клієнтів, у яких ще немає бронювань. Перетини з уже
наявними бронюваннями неможливі: кожен запис перевіряє обмеження
booking_no_overlap_per_unit, і конфліктний запис просто пропускається.

Усі імена, телефони й адреси пошти вигадані; паролі — лише для локальної демонстрації.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction

from accounts.models import User
from bookings.models import Booking, BookingEvent
from bookings.services import calculate_late_fee, money
from catalog.models import EquipmentType, EquipmentUnit, Tariff

DEMO_PASSWORD = "demo-pass-123"

# (назва, категорія, опис, ціна за добу, кількість екземплярів, технічна перерва в днях).
# Порядок не змінювати: від позиції залежать інвентарні номери INV-<позиція>-<номер>.
EQUIPMENT = [
    ("Камера Sony A7 III", "Фото й відео", "Повнокадрова бездзеркальна камера, 24 Мп, відео 4K.", "900.00", 3, 1),
    ("Об'єктив 24-70 мм f/2.8", "Фото й відео", "Універсальний зум-об'єктив для репортажу й портрета.", "450.00", 2, 1),
    ("Світлодіодна панель 60 Вт", "Світло", "Постійне світло з регулюванням яскравості й температури кольору.", "300.00", 4, 1),
    ("Намет на 3 особи", "Туризм", "Двошаровий намет, вага 2,8 кг. Після оренди сушиться й перевіряється.", "200.00", 5, 2),
    ("Перфоратор 800 Вт", "Інструменти", "SDS-plus, три режими роботи, кейс і набір бурів.", "250.00", 2, 1),
    ("Камера Canon EOS R6", "Фото й відео", "Повнокадрова камера зі стабілізацією матриці, 20 Мп.", "850.00", 2, 1),
    ("Об'єктив 50 мм f/1.8", "Фото й відео", "Світлосильний фікс для портретів і зйомки при слабкому світлі.", "200.00", 3, 0),
    ("Штатив Manfrotto", "Фото й відео", "Алюмінієвий штатив до 160 см з кульовою головою.", "120.00", 4, 0),
    ("Стабілізатор DJI RS 3", "Фото й відео", "Триосьовий стабілізатор для бездзеркальних камер до 3 кг.", "400.00", 2, 1),
    ("Квадрокоптер DJI Mini 4 Pro", "Дрони", "Вага до 250 г, відео 4K, три акумулятори в комплекті.", "1100.00", 2, 1),
    ("Квадрокоптер DJI Air 3", "Дрони", "Дві камери, політ до 46 хв, захист від зіткнень.", "1400.00", 1, 2),
    ("Софтбокс 60×90 см", "Світло", "Для студійного світла: м'яке розсіяне освітлення.", "150.00", 3, 0),
    ("Петличний радіомікрофон", "Звук", "Бездротова система на два передавачі, приймач на камеру.", "250.00", 3, 0),
    ("Портативна акустика 200 Вт", "Звук", "Колонка з акумулятором для заходів просто неба, мікрофонний вхід.", "350.00", 2, 1),
    ("Спальник до −5 °C", "Туризм", "Спальний мішок-кокон. Після кожної оренди хімчистка.", "90.00", 6, 2),
    ("Туристичний пальник з газом", "Туризм", "Компактний пальник, балон 450 г, вітрозахист.", "70.00", 4, 0),
    ("Гірський велосипед", "Спорт", "Розмір M, 29\", гідравлічні гальма, шолом у комплекті.", "350.00", 4, 1),
    ("Сапборд надувний", "Спорт", "Дошка 320 см з веслом, насосом і рятувальним жилетом.", "400.00", 3, 1),
    ("Шуруповерт акумуляторний", "Інструменти", "18 В, два акумулятори, набір біт.", "150.00", 3, 0),
    ("Лазерний нівелір", "Інструменти", "Хрестова лінія, дальність 20 м, штатив у комплекті.", "200.00", 2, 0),
]

# (логін, ім'я, прізвище, телефон). client1 і client2 — сценарні клієнти з README.
CLIENTS = [
    ("client1", "Іван", "Клієнтенко", "+380501110001"),
    ("client2", "Олена", "Орендаренко", "+380501110002"),
    ("andrii", "Андрій", "Мельник", "+380671234501"),
    ("sofiia", "Софія", "Бондаренко", "+380931234502"),
    ("dmytro", "Дмитро", "Ковальчук", "+380661234503"),
    ("yuliia", "Юлія", "Шевчук", "+380501234504"),
    ("taras", "Тарас", "Ткаченко", "+380971234505"),
    ("kateryna", "Катерина", "Лисенко", "+380631234506"),
    ("maksym", "Максим", "Савченко", "+380681234507"),
    ("anastasiia", "Анастасія", "Руденко", "+380991234508"),
    ("oleh", "Олег", "Мороз", "+380731234509"),
    ("iryna", "Ірина", "Поліщук", "+380951234510"),
]

# Скільки днів назад і вперед від сьогодні генерується історія бронювань.
HISTORY_DAYS_BACK = 60
HISTORY_DAYS_AHEAD = 45

MANAGER_CANCEL_REASONS = [
    "Екземпляр на позаплановому ремонті.",
    "Клієнт не підтвердив бронювання телефоном.",
    "Пошкоджено під час попередньої оренди, замінюємо.",
]


class Command(BaseCommand):
    help = "Створює демонстраційних користувачів, каталог, тарифи й бронювання"

    @transaction.atomic
    def handle(self, *args, **options):
        today = date.today()
        manager = self.create_user("manager", "Марія", "Менеджерська", "+380500000000", User.Role.MANAGER)
        clients = [self.create_user(u, f, l, p, User.Role.CLIENT) for u, f, l, p in CLIENTS]

        tariff_start = today - timedelta(days=HISTORY_DAYS_BACK + 30)
        for index, (name, category, description, price, count, turnaround) in enumerate(EQUIPMENT, start=1):
            etype, _ = EquipmentType.objects.get_or_create(
                name=name,
                defaults={"category": category, "description": description, "turnaround_days": turnaround},
            )
            Tariff.objects.get_or_create(
                equipment_type=etype, valid_from=tariff_start, defaults={"price_per_day": Decimal(price)}
            )
            for n in range(1, count + 1):
                EquipmentUnit.objects.get_or_create(
                    inventory_number=f"INV-{index:02d}-{n:03d}", defaults={"equipment_type": etype}
                )

        scenario = self.create_scenario_bookings(today, manager)
        history = self.create_history(today, manager, clients)

        self.stdout.write(self.style.SUCCESS(
            f"Демо-дані готові: {EquipmentType.objects.count()} позицій каталогу, "
            f"{EquipmentUnit.objects.count()} екземплярів, {len(clients)} клієнтів; "
            f"нових бронювань: {scenario + history}.\n"
            f"Вхід: manager, client1 … або логіни з CLIENTS; пароль: {DEMO_PASSWORD}"
        ))

    # ---------- користувачі ----------

    def create_user(self, username, first, last, phone, role):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first,
                "last_name": last,
                "phone": phone,
                "email": f"{username}@example.com",
                "role": role,
            },
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
        return user

    # ---------- допоміжне ----------

    @staticmethod
    def price_of(unit):
        return unit.equipment_type.tariffs.order_by("-valid_from").first().price_per_day

    def save_booking(self, *, unit, client, start, end, status, manager, returned_on=None, cancel=None):
        """Створює бронювання з подіями або повертає None, якщо період уже зайнятий.

        Дати можуть бути в минулому, тому запис іде напряму, в обхід форми.
        Обмеження перетину однаково перевіряє PostgreSQL: кожен запис у власній
        точці збереження, і конфліктний просто пропускається.
        """
        price = self.price_of(unit)
        try:
            with transaction.atomic():
                booking = Booking.objects.create(
                    unit=unit,
                    client=client,
                    start_date=start,
                    end_date=end,
                    status=status,
                    price_per_day=price,
                    total_price=price * (end - start).days,
                    buffer_days=unit.equipment_type.turnaround_days,
                )
                BookingEvent.objects.create(booking=booking, kind=BookingEvent.Kind.CREATED, actor=client)
                if status in (Booking.Status.ISSUED, Booking.Status.RETURNED):
                    BookingEvent.objects.create(booking=booking, kind=BookingEvent.Kind.ISSUED, actor=manager)
                if status == Booking.Status.RETURNED:
                    booking.returned_on = returned_on or end
                    booking.late_days, booking.late_fee = calculate_late_fee(price, end, booking.returned_on)
                    booking.save(update_fields=["returned_on", "late_days", "late_fee"])
                    comment = (
                        f"Запізнення {booking.late_days} дн., доплата {money(booking.late_fee)} грн."
                        if booking.late_days else ""
                    )
                    BookingEvent.objects.create(
                        booking=booking, kind=BookingEvent.Kind.RETURNED, actor=manager, comment=comment
                    )
                if status == Booking.Status.CANCELLED:
                    actor, comment = cancel or (client, "")
                    BookingEvent.objects.create(
                        booking=booking, kind=BookingEvent.Kind.CANCELLED, actor=actor, comment=comment
                    )
        except IntegrityError:
            return None
        return booking

    # ---------- сценарні бронювання ----------

    def create_scenario_bookings(self, today, manager):
        """Конкретні випадки для демонстрації панелі менеджера (лише в порожній базі)."""
        if Booking.objects.exists():
            return 0
        client1 = User.objects.get(username="client1")
        client2 = User.objects.get(username="client2")
        # (інв. номер, клієнт, початок, кінець, статус, фактичне повернення)
        scenario = [
            ("INV-01-001", client1, 0, 3, Booking.Status.CONFIRMED, None),     # видача сьогодні
            ("INV-02-001", client2, -1, 2, Booking.Status.CONFIRMED, None),    # не забрали вчасно
            ("INV-04-001", client1, 4, 7, Booking.Status.CONFIRMED, None),     # майбутня
            ("INV-03-001", client2, -3, 2, Booking.Status.ISSUED, None),       # видано, в строк
            ("INV-05-001", client1, -7, -2, Booking.Status.ISSUED, None),      # прострочено
            ("INV-05-001", client2, 0, 2, Booking.Status.CONFIRMED, None),     # не можна видати: попередню не повернули
            ("INV-01-002", client2, -14, -10, Booking.Status.RETURNED, -8),    # повернено із запізненням
        ]
        created = 0
        for inventory, client, start, end, status, returned in scenario:
            booking = self.save_booking(
                unit=EquipmentUnit.objects.get(inventory_number=inventory),
                client=client,
                start=today + timedelta(days=start),
                end=today + timedelta(days=end),
                status=status,
                manager=manager,
                returned_on=today + timedelta(days=returned) if returned is not None else None,
            )
            created += booking is not None
        return created

    # ---------- історія бронювань ----------

    def create_history(self, today, manager, clients):
        """Історія оренд демо-клієнтів, у яких ще немає жодного бронювання.

        Для кожного екземпляра будується послідовність оренд від
        today − HISTORY_DAYS_BACK до today + HISTORY_DAYS_AHEAD з паузами
        й технічною перервою між ними. Статус залежить від дат:
        минулі — повернені (частина із запізненням) або скасовані;
        поточні — видані; майбутні — підтверджені або скасовані.
        Генератор випадкових чисел із фіксованим зерном дає однаковий результат щоразу.
        """
        free_clients = [c for c in clients if not c.bookings.exists()]
        if not free_clients:
            return 0

        rng = random.Random(2026)
        window_start = today - timedelta(days=HISTORY_DAYS_BACK)
        window_end = today + timedelta(days=HISTORY_DAYS_AHEAD)
        units = (
            EquipmentUnit.objects.filter(status=EquipmentUnit.Status.AVAILABLE)
            .select_related("equipment_type")
            .order_by("inventory_number")
        )
        created = 0
        for unit in units:
            # Екземпляри зі сценарними чи вже наявними активними бронюваннями не чіпаємо,
            # щоб не створити другу «видану» оренду того самого екземпляра.
            if unit.bookings.filter(status__in=Booking.ACTIVE_STATUSES).exists():
                continue
            # Частина екземплярів лишається зовсім вільною — щоб було що бронювати.
            if rng.random() < 0.3:
                continue

            buffer = timedelta(days=unit.equipment_type.turnaround_days)
            cursor = window_start + timedelta(days=rng.randint(0, 10))
            while cursor < window_end:
                start = cursor + timedelta(days=rng.randint(3, 14))
                end = start + timedelta(days=rng.randint(1, 5))
                if start >= window_end:
                    break
                client = rng.choice(free_clients)
                returned_on, cancel = None, None

                if end <= today:  # оренда вже мала завершитися
                    roll = rng.random()
                    if roll < 0.12:
                        status = Booking.Status.CANCELLED
                        cancel = self.random_cancel(rng, client, manager)
                    else:
                        status = Booking.Status.RETURNED
                        late = rng.randint(1, 3) if roll > 0.85 else 0
                        returned_on = min(end + timedelta(days=late), today)
                elif start <= today:  # оренда триває зараз
                    status = Booking.Status.ISSUED
                else:  # майбутня
                    status = Booking.Status.CONFIRMED
                    if rng.random() < 0.1:
                        status = Booking.Status.CANCELLED
                        cancel = self.random_cancel(rng, client, manager)

                booking = self.save_booking(
                    unit=unit, client=client, start=start, end=end, status=status,
                    manager=manager, returned_on=returned_on, cancel=cancel,
                )
                created += booking is not None
                # Наступна оренда — після фактичного повернення й технічної перерви.
                cursor = max(end, returned_on or end) + buffer
        return created

    @staticmethod
    def random_cancel(rng, client, manager):
        if rng.random() < 0.5:
            return client, ""
        return manager, rng.choice(MANAGER_CANCEL_REASONS)
