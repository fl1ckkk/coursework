# bookings.0003_booking_no_overlap

| | |
|---|---|
| Файл | `bookings/migrations/0003_booking_no_overlap.py` |
| Тип | Згенерована (`makemigrations --name booking_no_overlap`) з моделі `Booking` |
| Залежить від | `bookings.0002_btree_gist_extension` |
| Дата | 2026-11-24 |

## Мета

Реалізувати головне бізнес-правило: **активні бронювання одного екземпляра
не можуть перетинатися в часі**, і перевіряти його в базі даних.

### Чому не перевірки в коді

Перевірка «спершу SELECT, потім INSERT» має вразливість: два клієнти одночасно
бачать, що екземпляр вільний, і обидва створюють бронювання. Обмеження
`EXCLUDE` у PostgreSQL робить перевірку й вставку однією атомарною дією:
друга транзакція отримає помилку. Це перевіряє тест `ConcurrentBookingTests`.

## Зміни в схемі

Обмеження `booking_no_overlap_per_unit` на таблиці `bookings_booking`:

| Частина | Значення |
|---|---|
| Індекс | GiST |
| Умова 1 | `unit_id WITH =` — той самий екземпляр |
| Умова 2 | `daterange(start_date, end_date, '[)') WITH &&` — періоди перетинаються |
| Діє для | рядків зі `status IN ('pending', 'confirmed', 'issued')` |

Обмеження забороняє вставити рядок, для якого вже існує інший рядок, де
**обидві** умови істинні.

- `'[)'` — напіввідкритий діапазон: дата видачі входить, дата повернення ні.
  Тому бронювання 1–3 і 3–5 грудня не конфліктують.
- Скасовані, відхилені й повернені бронювання не блокують екземпляр завдяки `WHERE`.

У моделі для виклику SQL-функції `daterange` використано клас
`DateRange(Func)` з `bookings/models.py`.

## SQL

```sql
ALTER TABLE "bookings_booking"
  ADD CONSTRAINT "booking_no_overlap_per_unit"
  EXCLUDE USING GIST (
    "unit_id" WITH =,
    (daterange("start_date", "end_date", '[)')) WITH &&
  )
  WHERE ("status" IN ('pending', 'confirmed', 'issued'));
```

## Обробка в застосунку

`bookings/services.py → create_booking` перехоплює `IntegrityError` з назвою
цього обмеження і перетворює його на `BookingConflict` з повідомленням
«Цей екземпляр уже заброньовано на частину вибраного періоду».

## Відкат

```bash
python manage.py migrate bookings 0002
```

Видаляє обмеження (`ALTER TABLE ... DROP CONSTRAINT booking_no_overlap_per_unit`).
Дані не змінюються, але база знову дозволить перетини.

Якщо в базі вже є перетинні активні бронювання, повторне застосування
міграції завершиться помилкою: спершу їх потрібно знайти й виправити:

```sql
SELECT a.id, b.id, a.unit_id
FROM bookings_booking a
JOIN bookings_booking b
  ON a.unit_id = b.unit_id AND a.id < b.id
 AND daterange(a.start_date, a.end_date, '[)') && daterange(b.start_date, b.end_date, '[)')
WHERE a.status IN ('pending','confirmed','issued')
  AND b.status IN ('pending','confirmed','issued');
```

## Перевірка

Автоматично: `python manage.py test bookings` (тести перетину, суміжних періодів,
звільнення після скасування, обходу сервісу й паралельних запитів).

Вручну в `psql` (з існуючими `unit_id = 1` і `client_id = 1`):

```sql
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, created_at, updated_at)
VALUES (1, 1, '2026-12-01', '2026-12-05', 'pending', 100, 400, now(), now());

-- Помилка: conflicting key value violates exclusion constraint "booking_no_overlap_per_unit"
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, created_at, updated_at)
VALUES (1, 1, '2026-12-04', '2026-12-07', 'pending', 100, 300, now(), now());

-- Успіх: період починається в день повернення
INSERT INTO bookings_booking (unit_id, client_id, start_date, end_date, status,
  price_per_day, total_price, created_at, updated_at)
VALUES (1, 1, '2026-12-05', '2026-12-07', 'pending', 100, 200, now(), now());
```
