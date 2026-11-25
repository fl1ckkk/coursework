# bookings.0004_auto_confirm_bookings

| | |
|---|---|
| Файл | `bookings/migrations/0004_auto_confirm_bookings.py` |
| Тип | Згенерована (`makemigrations --name auto_confirm_bookings`) + вручну дописана операція перенесення даних |
| Залежить від | `bookings.0003_booking_no_overlap` |
| Дата | 2026-11-25 |

## Мета

Перейти від ручного погодження заявок менеджером до автоматичного підтвердження.

Заявка, яка пройшла всі перевірки під час створення (дати, стан екземпляра,
тариф, відсутність перетину), одразу отримує статус «Підтверджено».
Недійсну заявку система відхиляє ще до збереження, тому статуси
«Очікує погодження» (`pending`) і «Відхилено» (`rejected`) більше не потрібні.

## Зміни

| Що | Було | Стало |
|---|---|---|
| Статуси бронювання | `pending`, `confirmed`, `issued`, `returned`, `rejected`, `cancelled` | `confirmed`, `issued`, `returned`, `cancelled` |
| Статус за замовчуванням | `pending` | `confirmed` |
| Види подій | `created`, `confirmed`, `rejected`, `cancelled`, `issued`, `returned` | `created`, `cancelled`, `issued`, `returned` |
| Умова `booking_no_overlap_per_unit` | `status IN ('pending', 'confirmed', 'issued')` | `status IN ('confirmed', 'issued')` |

## Операції (у порядку виконання)

1. **`RunPython(convert_statuses)`** — перенесення даних, написано вручну:

   | Таблиця | Було | Стало | Чому |
   |---|---|---|---|
   | `bookings_booking` | `pending` | `confirmed` | Заявка пройшла перевірки при створенні |
   | `bookings_booking` | `rejected` | `cancelled` | Як і скасована, не займає екземпляр |
   | `bookings_bookingevent` | `confirmed` | видаляється | Підтвердження тепер входить у подію `created` |
   | `bookings_bookingevent` | `rejected` | `cancelled` | Коментар із причиною зберігається |

   Виконується першою, поки діє старе обмеження. Перенесення `pending` → `confirmed`
   не може створити перетинів, бо обидва статуси вже були активними.

2. **`RemoveConstraint`** — видаляє старе обмеження перетину.
3. **`AlterField`** (`Booking.status`, `BookingEvent.kind`) — новий перелік значень
   і значення за замовчуванням. У базі даних це нічого не змінює: перелік
   значень і значення за замовчуванням Django перевіряє на рівні застосунку.
4. **`AddConstraint`** — те саме обмеження з новою умовою.

## Чому `RunPython`, а не SQL

Django не генерує перенесення даних автоматично: `makemigrations` бачить лише
зміну схеми. Операцію дописано вручну. У ній використано
`apps.get_model(...)` — історичну версію моделі на момент міграції, а не
імпорт із `models.py`, бо поточна модель у майбутньому може змінитися.

## SQL

```sql
-- Raw Python operation (convert_statuses): SQL не показується
ALTER TABLE "bookings_booking" DROP CONSTRAINT "booking_no_overlap_per_unit";
-- Alter field status on booking: (no-op)
-- Alter field kind on bookingevent: (no-op)
ALTER TABLE "bookings_booking" ADD CONSTRAINT "booking_no_overlap_per_unit"
  EXCLUDE USING GIST ("unit_id" WITH =, (daterange("start_date", "end_date", '[)')) WITH &&)
  WHERE ("status" IN ('confirmed', 'issued'));
```

Еквівалент `convert_statuses` у SQL (для пояснення):

```sql
UPDATE bookings_booking SET status = 'confirmed' WHERE status = 'pending';
UPDATE bookings_booking SET status = 'cancelled' WHERE status = 'rejected';
DELETE FROM bookings_bookingevent WHERE kind = 'confirmed';
UPDATE bookings_bookingevent SET kind = 'cancelled' WHERE kind = 'rejected';
```

## Відкат

```bash
python manage.py migrate bookings 0003
```

Обмеження повертається до старої умови. Для даних відкат порожній
(`RunPython.noop`): статуси `confirmed` і `cancelled` допустимі й у старій
схемі, тому дані лишаються коректними. Видалені події `confirmed` не відновлюються.

## Перевірка

Міграцію перевірено на базі, де до її застосування були записи зі старими статусами:

| До | Після |
|---|---|
| бронювання `pending` | `confirmed` |
| бронювання `rejected` | `cancelled` |
| подія `confirmed` | видалена |
| подія `rejected` з коментарем «Немає паспорта» | `cancelled` з тим самим коментарем |

Після цього перевірено відкат до 0003 і повторне застосування.

Перевірка умови обмеження в базі:

```sql
SELECT pg_get_constraintdef(oid) FROM pg_constraint
WHERE conname = 'booking_no_overlap_per_unit';
-- ... WHERE ((status)::text = ANY (ARRAY['confirmed', 'issued']))
```

Автоматично: тест `ConstraintConsistencyTests` перевіряє, що умова обмеження
збігається з `Booking.ACTIVE_STATUSES` у коді.
