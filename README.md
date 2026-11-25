# Оренда обладнання з календарем доступності

Курсова робота з дисципліни «Веб-технології та веб-дизайн» (варіант 12).

Вебсистема, у якій клієнт вибирає обладнання з каталогу, бронює конкретний
екземпляр на період і бачить вартість, а менеджер погоджує заявки, видає та
приймає обладнання. Головне правило: **активні бронювання одного екземпляра
не можуть перетинатися в часі**. Його перевіряє сама база даних, тому воно діє
і для одночасних запитів.

Детальна документація: [`documentation/`](documentation/README.md).

## Стек

| Компонент | Версія |
|---|---|
| Python | 3.12 або новіший |
| Django | 5.2 (LTS) |
| PostgreSQL | 16 або новіша, перевірено на 16 і 17 (потрібне розширення `btree_gist`, входить у стандартну поставку) |
| psycopg | 3.3 |

## Запуск

### 1. Отримати код і встановити залежності

```bash
git clone https://github.com/fl1ckkk/coursework.git
cd coursework
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Налаштувати середовище

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Відкрийте `.env` і задайте `DJANGO_SECRET_KEY` та пароль бази даних.

### 3. Підготувати базу даних

Варіант А: PostgreSQL у Docker (значення беруться з `.env`):

```bash
docker compose up -d
```

Варіант Б: встановлений PostgreSQL. Створіть користувача й базу, назви яких указані в `.env`:

```sql
CREATE USER rental WITH PASSWORD 'ваш-пароль' CREATEDB;
CREATE DATABASE rental OWNER rental;
```

Право `CREATEDB` потрібне лише для запуску тестів: Django створює окрему тестову базу.

### 4. Застосувати міграції та завантажити демо-дані

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser   # для входу в /admin/
```

`seed_demo` створює синтетичних користувачів `manager`, `client1`, `client2`
з паролем `demo-pass-123`, обладнання й тарифи, а в порожній базі ще й бронювання
в різних станах (видача сьогодні, прострочене, повернене із запізненням тощо)
для демонстрації панелі менеджера. Повторний запуск безпечний.

### 5. Запустити

```bash
python manage.py runserver
```

- Каталог: http://127.0.0.1:8000/
- Адміністрування: http://127.0.0.1:8000/admin/

### 6. Запустити тести

```bash
python manage.py test
```

Навантажувальне тестування: [`documentation/load-testing.md`](documentation/load-testing.md).

## Структура

```
config/          налаштування Django, маршрути
accounts/        користувачі й ролі (клієнт, менеджер)
catalog/         типи обладнання, екземпляри, тарифи, сторінки каталогу
bookings/        бронювання, журнал подій, бізнес-правила (services.py)
templates/       HTML-шаблони
static/          стилі (світла й темна теми, адаптивна верстка)
loadtest/        сценарії навантажувального тестування (Locust)
documentation/   документація проєкту та міграцій
```
