# bookings.0005_booking_buffer_days

| | |
|---|---|
| Файл | `bookings/migrations/0005_booking_buffer_days.py` |
| Тип | Згенерована (`makemigrations --name booking_buffer_days`) |
| Залежить від | `bookings.0004_auto_confirm_bookings`, `catalog.0002_equipmenttype_turnaround_days` |
| Дата | 2026-11-25 |

## Мета

Врахувати технічну перерву між орендами в головному правилі системи.
Тепер екземпляр вважається зайнятим не до дати повернення, а до
**дати повернення + технічна перерва**, і цю умову перевіряє PostgreSQL.

## Зміни в схемі

### Нове поле `bookings_booking.buffer_days`

| Тип у БД | За замовчуванням |
|---|---|
| `smallint NOT NULL CHECK (buffer_days >= 0)` | `0` (на рівні бази, `db_default`) |

Під час створення бронювання сюди копіюється `turnaround_days` типу обладнання.

**Чому знімок, а не посилання на тип.** Якщо менеджер збільшить перерву,
наприклад з 1 до 5 днів, вже створені бронювання, які стоять впритул,
не стануть порушенням правила. Нове значення діє лише для нових бронювань.
Так само зберігається ціна (`price_per_day`).

**Чому `db_default`, а не лише `default`.** Значення за замовчуванням лишається
в самій базі, тому запис, вставлений напряму SQL-запитом (наприклад,
у прикладах перевірки міграції 0003), теж отримує 0.

### Оновлене обмеження `booking_no_overlap_per_unit`

| | Було (0004) | Стало |
|---|---|---|
| Період | `daterange(start_date, end_date, '[)')` | `daterange(start_date, end_date + buffer_days, '[)')` |
| Екземпляр | `unit_id WITH =` | без змін |
| Діє для | `status IN ('confirmed', 'issued')` | без змін |

У PostgreSQL `date + integer` дає дату через указану кількість днів,
тому вираз `end_date + buffer_days` обчислюється прямо в індексі.
У моделі для цього використано `ExpressionWrapper(F("end_date") + F("buffer_days"))`.

Приклад при перерві 1 день: оренда 1–3 грудня займає екземпляр на `[1; 4)`.

| Нова оренда | Результат |
|---|---|
| 3–5 грудня | ❌ відхилено: 3 грудня — день перерви |
| 4–6 грудня | ✅ дозволено |
| 30 листопада – 1 грудня (своя перерва 1 день) | ❌ відхилено: її перерва припадає на 1 грудня |

Перерва йде після **кожної** оренди, тому обмеження симетричне:
попередня оренда теж не може закінчитися впритул до наступної.

## SQL

```sql
ALTER TABLE "bookings_booking" DROP CONSTRAINT "booking_no_overlap_per_unit";

ALTER TABLE "bookings_booking"
  ADD COLUMN "buffer_days" smallint DEFAULT 0 NOT NULL CHECK ("buffer_days" >= 0);

ALTER TABLE "bookings_booking" ADD CONSTRAINT "booking_no_overlap_per_unit"
  EXCLUDE USING GIST (
    "unit_id" WITH =,
    (daterange("start_date", ("end_date" + "buffer_days"), '[)')) WITH &&
  )
  WHERE ("status" IN ('confirmed', 'issued'));
```

## Вплив на наявні дані

Наявні бронювання отримують `buffer_days = 0`, тобто для них нічого не
змінюється. Тому повторне створення обмеження не може завершитися помилкою
через бронювання, які раніше стояли впритул.

## Відкат

```bash
python manage.py migrate bookings 0004
```

Обмеження повертається до періоду без перерви, стовпець `buffer_days`
видаляється разом зі значеннями.

## Перевірка

Перевірено на базі з демо-даними: міграція застосована, у наявних бронювань
`buffer_days = 0`; виконано відкат до `0004` і `catalog.0001` та повторне застосування.

Автоматично: група тестів `TurnaroundTests` у `bookings/tests.py`.

Вручну в `psql` (екземпляр `unit_id = 1` без інших бронювань у грудні):

```sql
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, buffer_days, created_at, updated_at)
VALUES (1, 1, '2026-12-01', '2026-12-03', 'confirmed', 100, 200, 1, now(), now());

-- Помилка: 3 грудня — день технічної перерви
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, created_at, updated_at)
VALUES (1, 1, '2026-12-03', '2026-12-05', 'confirmed', 100, 200, now(), now());

-- Успіх
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, created_at, updated_at)
VALUES (1, 1, '2026-12-04', '2026-12-06', 'confirmed', 100, 200, now(), now());
```
