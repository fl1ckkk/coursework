# bookings.0006_extension_and_late_return

| | |
|---|---|
| Файл | `bookings/migrations/0006_extension_and_late_return.py` |
| Тип | Згенерована (`makemigrations --name extension_and_late_return`) |
| Залежить від | `bookings.0005_booking_buffer_days` |
| Дата | 2026-11-25 |

## Мета

Закрити дві вимоги варіанта 12:

1. **«Визначити правила продовження»**: клієнт або менеджер продовжує оренду,
   і в журналі подій це має окремий вид події.
2. **«Перевірити повернення із запізненням»**: під час прийому обладнання
   зберігаються фактична дата повернення, кількість діб запізнення й доплата.

Самі правила реалізовано в `bookings/services.py` (див. [modules/bookings.md](../modules/bookings.md)).
Міграція додає потрібні для них поля.

## Зміни в схемі

### `bookings_booking`

| Поле | Тип у БД | За замовчуванням | Призначення |
|---|---|---|---|
| `returned_on` | `date NULL` | — | Фактична дата повернення; заповнюється, коли менеджер приймає обладнання |
| `late_days` | `smallint NOT NULL CHECK (late_days >= 0)` | `0` (`db_default`) | Скільки діб минуло після `end_date` до фактичного повернення |
| `late_fee` | `numeric(12,2) NOT NULL` | `0` (`db_default`) | Доплата за запізнення, грн |

Нове обмеження:

| Назва | Умова |
|---|---|
| `booking_late_fee_non_negative` | `late_fee >= 0` |

### `bookings_bookingevent.kind`

Додано значення `extended` («Продовжено»). Перелік значень перевіряє Django,
тому в базі даних ця зміна нічого не робить (`no-op`).

## SQL

```sql
ALTER TABLE "bookings_booking"
  ADD COLUMN "late_days" smallint DEFAULT 0 NOT NULL CHECK ("late_days" >= 0);
ALTER TABLE "bookings_booking"
  ADD COLUMN "late_fee" numeric(12, 2) DEFAULT 0 NOT NULL;
ALTER TABLE "bookings_booking"
  ADD COLUMN "returned_on" date NULL;
-- Alter field kind on bookingevent: (no-op)
ALTER TABLE "bookings_booking"
  ADD CONSTRAINT "booking_late_fee_non_negative" CHECK ("late_fee" >= 0);
```

Значення за замовчуванням лишаються в базі (`db_default`), тому записи,
вставлені напряму SQL-запитом, теж отримують 0.

## Вплив на наявні дані

Наявні бронювання отримують `late_days = 0`, `late_fee = 0`, `returned_on = NULL`.
Для бронювань, повернених до цієї міграції, фактична дата повернення невідома,
тому вона лишається порожньою, а доплата заднім числом не нараховується.

## Відкат

```bash
python manage.py migrate bookings 0005
```

Три стовпці й обмеження видаляються разом зі значеннями. Події `extended`
лишаються в журналі, але після відкату Django показуватиме їх як сирий код
`extended`, бо цього значення не буде в переліку.

## Перевірка

Міграцію застосовано на базі, де до неї вже були бронювання у статусах
`confirmed` і `returned`: обидва отримали `late_days = 0`, `late_fee = 0.00`,
`returned_on = NULL`. Перевірено відкат до `0005` і повторне застосування.

Обмеження в дії:

```sql
UPDATE bookings_booking SET late_fee = -1 WHERE id = 1;
-- ERROR: new row for relation "bookings_booking"
--        violates check constraint "booking_late_fee_non_negative"
```

Автоматично: групи тестів `ExtensionTests` і `LateReturnTests` у `bookings/tests.py`.
