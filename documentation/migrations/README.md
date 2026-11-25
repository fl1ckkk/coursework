# Міграції бази даних

## Інструмент

**Django migrations** — вбудована система міграцій Django 5.2.

- Міграції лежать у `<модуль>/migrations/` і є Python-файлами, які зберігаються в Git.
- Django веде облік застосованих міграцій у таблиці `django_migrations`.
- Більшість міграцій генерується з моделей (`makemigrations`); операції, яких
  немає в моделях (наприклад, увімкнення розширення PostgreSQL), пишуться вручну.

Чому не окремий інструмент (Alembic, Flyway, Liquibase): Django-міграції
генеруються з тих самих моделей, з якими працює код, тому схема й код
не розходяться. Окремий інструмент дублював би опис схеми.

## Команди

| Дія | Команда |
|---|---|
| Застосувати всі міграції | `python manage.py migrate` |
| Переглянути стан | `python manage.py showmigrations` |
| Згенерувати міграцію після зміни моделей | `python manage.py makemigrations <модуль> --name <назва>` |
| Переглянути SQL міграції | `python manage.py sqlmigrate <модуль> <номер>` |
| Відкотити до міграції N | `python manage.py migrate <модуль> <N>` |
| Відкотити всі міграції модуля | `python manage.py migrate <модуль> zero` |
| Перевірити, що моделі й міграції збігаються | `python manage.py makemigrations --check --dry-run` |

## Правила проєкту

1. Кожна міграція має змістовну назву (`--name booking_no_overlap`), а не `0004_auto_...`.
2. Застосовану й запушену міграцію не редагують: зміни робляться новою міграцією.
3. Для кожної міграції в цій папці є файл `<модуль>_<номер>_<назва>.md` за шаблоном нижче.
4. Перед комітом: `makemigrations --check` не знаходить змін, а `python manage.py test` проходить.

## Порядок застосування

Залежності визначають порядок: спочатку користувачі й каталог, потім бронювання,
бо бронювання посилаються на них зовнішніми ключами.

```
accounts.0001_initial ─┐
catalog.0001_initial ──┼─▶ bookings.0001_initial ─▶ bookings.0002_btree_gist_extension ─▶ bookings.0003_booking_no_overlap
                                                                                                  │
                                                                                                  ▼
                                                                                  bookings.0004_auto_confirm_bookings
                                                                                                  │
catalog.0002_equipmenttype_turnaround_days ───────────────────────────────────────────────────────┤
                                                                                                  ▼
                                                                                  bookings.0005_booking_buffer_days
                                                                                                  │
                                                                                                  ▼
                                                                                  bookings.0006_extension_and_late_return
```

## Перелік міграцій

| Міграція | Що робить | Опис |
|---|---|---|
| `accounts.0001_initial` | Таблиця користувачів із роллю | [accounts_0001_initial.md](accounts_0001_initial.md) |
| `catalog.0001_initial` | Типи обладнання, екземпляри, тарифи | [catalog_0001_initial.md](catalog_0001_initial.md) |
| `catalog.0002_equipmenttype_turnaround_days` | Технічна перерва між орендами для типу обладнання | [catalog_0002_equipmenttype_turnaround_days.md](catalog_0002_equipmenttype_turnaround_days.md) |
| `bookings.0001_initial` | Бронювання, журнал подій, CHECK-обмеження | [bookings_0001_initial.md](bookings_0001_initial.md) |
| `bookings.0002_btree_gist_extension` | Розширення PostgreSQL `btree_gist` | [bookings_0002_btree_gist_extension.md](bookings_0002_btree_gist_extension.md) |
| `bookings.0003_booking_no_overlap` | Заборона перетину бронювань | [bookings_0003_booking_no_overlap.md](bookings_0003_booking_no_overlap.md) |
| `bookings.0004_auto_confirm_bookings` | Автопідтвердження: прибрано статуси `pending` і `rejected`, перенесено дані, оновлено умову обмеження | [bookings_0004_auto_confirm_bookings.md](bookings_0004_auto_confirm_bookings.md) |
| `bookings.0005_booking_buffer_days` | Знімок перерви в бронюванні; обмеження перетину з урахуванням перерви | [bookings_0005_booking_buffer_days.md](bookings_0005_booking_buffer_days.md) |
| `bookings.0006_extension_and_late_return` | Фактична дата повернення, діб запізнення, доплата; подія «Продовжено» | [bookings_0006_extension_and_late_return.md](bookings_0006_extension_and_late_return.md) |

Стандартні міграції Django (`auth`, `admin`, `contenttypes`, `sessions`)
не описуються окремо: вони не є власною розробкою.

## Шаблон опису міграції

```markdown
# <модуль>.<номер>_<назва>

| | |
|---|---|
| Файл | `<модуль>/migrations/<файл>.py` |
| Тип | Згенерована / Написана вручну |
| Залежить від | ... |
| Дата | РРРР-ММ-ДД |

## Мета
Навіщо потрібна міграція.

## Зміни в схемі
Таблиці, поля, обмеження, індекси.

## SQL
Вивід `python manage.py sqlmigrate <модуль> <номер>` (скорочено).

## Відкат
Команда й що станеться з даними.

## Перевірка
Як переконатися, що міграція працює.
```
