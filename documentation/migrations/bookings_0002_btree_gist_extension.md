# bookings.0002_btree_gist_extension

| | |
|---|---|
| Файл | `bookings/migrations/0002_btree_gist_extension.py` |
| Тип | Написана вручну |
| Залежить від | `bookings.0001_initial` |
| Дата | 2026-11-24 |

## Мета

Увімкнути розширення PostgreSQL `btree_gist`, без якого неможлива міграція 0003.

Обмеження `EXCLUDE` у 0003 будує GiST-індекс з двох частин:

- діапазон дат з оператором `&&` (перетинається) — GiST підтримує його сам;
- `unit_id` з оператором `=` — для звичайного цілого числа GiST цього не вміє.

`btree_gist` додає в GiST підтримку `=` для звичайних типів (цілих, рядків, дат).

## Чому вручну

Розширення не є частиною жодної моделі, тому `makemigrations` його не створює.
Використано готову операцію Django `BtreeGistExtension()`
з `django.contrib.postgres.operations`.

## Зміни в схемі

Нових таблиць немає. У базі з'являється розширення `btree_gist`.

## SQL

```sql
CREATE EXTENSION IF NOT EXISTS "btree_gist";
```

`sqlmigrate` для цієї міграції показує `(no-op)`, бо Django виконує операцію
лише при реальному `migrate`, перевіривши, чи розширення вже є.

## Права

Починаючи з PostgreSQL 13, `btree_gist` — довірене розширення: його може
увімкнути власник бази без прав суперкористувача. На старіших версіях
розширення має створити адміністратор: `CREATE EXTENSION btree_gist;`.

## Відкат

```bash
python manage.py migrate bookings 0001
```

Спершу відкочується 0003 (обмеження), потім видаляється розширення
(`DROP EXTENSION btree_gist`). Дані таблиць не змінюються.

## Перевірка

```sql
SELECT extname, extversion FROM pg_extension WHERE extname = 'btree_gist';
```
