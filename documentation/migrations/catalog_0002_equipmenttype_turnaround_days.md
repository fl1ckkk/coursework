# catalog.0002_equipmenttype_turnaround_days

| | |
|---|---|
| Файл | `catalog/migrations/0002_equipmenttype_turnaround_days.py` |
| Тип | Згенерована (`makemigrations --name equipmenttype_turnaround_days`) |
| Залежить від | `catalog.0001_initial` |
| Дата | 2026-11-25 |

## Мета

Додати налаштування **технічної перерви між орендами** для кожного типу
обладнання. Після повернення екземпляр кілька днів недоступний: його треба
перевірити, почистити, зарядити чи просушити. Різним типам потрібен різний час,
тому перерва задається для типу, а не однією цифрою на всю систему.

Менеджер змінює значення в адмінці (Типи обладнання → поле «технічна перерва, днів»).

## Зміни в схемі

| Таблиця | Поле | Тип у БД | Значення |
|---|---|---|---|
| `catalog_equipmenttype` | `turnaround_days` | `smallint NOT NULL CHECK (turnaround_days >= 0)` | 0–30, за замовчуванням 1 |

Верхню межу 30 днів перевіряє Django (валідатор у формі адмінки),
невід'ємність — сама база (`CHECK`).

## SQL

```sql
ALTER TABLE "catalog_equipmenttype"
  ADD COLUMN "turnaround_days" smallint DEFAULT 1 NOT NULL
  CHECK ("turnaround_days" >= 0);
ALTER TABLE "catalog_equipmenttype" ALTER COLUMN "turnaround_days" DROP DEFAULT;
```

Django тимчасово ставить `DEFAULT 1`, щоб заповнити наявні рядки, а потім
прибирає його: для нових записів значення підставляє застосунок.

## Вплив на наявні дані

Усі наявні типи обладнання отримують перерву 1 день. Уже створені бронювання
це не змінює: перерва копіюється в бронювання в момент його створення
(міграція [bookings.0005](bookings_0005_booking_buffer_days.md)).

## Відкат

```bash
python manage.py migrate catalog 0001
```

Спершу відкочується `bookings.0005`, бо вона залежить від цієї міграції.
Стовпець видаляється разом зі значеннями.

## Перевірка

```sql
SELECT name, turnaround_days FROM catalog_equipmenttype;
```

Перевірено на базі з демо-даними: усі 5 типів отримали значення 1.
