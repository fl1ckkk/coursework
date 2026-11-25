"""Сценарії навантажувального тестування (Locust).

Три типи віртуальних користувачів у пропорції, близькій до реальної:
  Guest   (6) — переглядає каталог, шукає, відкриває картки обладнання;
  Client  (3) — входить, бронює на випадкові дати, переглядає свої бронювання;
  Manager (1) — переглядає панель заявок із фільтрами.

Запуск і порядок підготовки бази — у documentation/load-testing.md.
"""

import random
import re
from datetime import date, timedelta
from itertools import count

from locust import HttpUser, between, task

CLIENTS = 100
LOAD_PASSWORD = "load-pass-123"
MANAGER = ("manager", "demo-pass-123")

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
TYPE_LINK_RE = re.compile(r'href="/equipment/(\d+)/"')
UNIT_OPTION_RE = re.compile(r'<option value="(\d+)"')

_client_numbers = count(1)


def csrf_token(response) -> str:
    match = CSRF_RE.search(response.text)
    if not match:
        response.failure("На сторінці немає CSRF-токена")
        return ""
    return match.group(1)


def login(user: HttpUser, username: str, password: str) -> None:
    with user.client.get("/login/", name="/login/", catch_response=True) as page:
        token = csrf_token(page)
    with user.client.post(
        "/login/",
        {"username": username, "password": password, "csrfmiddlewaretoken": token},
        name="/login/ [POST]",
        catch_response=True,
    ) as response:
        # Успішний вхід перенаправляє в каталог; помилка — та сама сторінка входу.
        if "/login/" in response.url:
            response.failure(f"Не вдалося увійти як {username}")


class Guest(HttpUser):
    weight = 6
    wait_time = between(1, 3)

    def on_start(self):
        response = self.client.get("/", name="/ (каталог)")
        self.type_ids = TYPE_LINK_RE.findall(response.text) or ["1"]

    @task(3)
    def catalog(self):
        self.client.get("/", name="/ (каталог)")

    @task(2)
    def search(self):
        query = random.choice(["камера", "намет", "світло", "об'єктив", "неіснуюче"])
        self.client.get("/", params={"q": query}, name="/?q= (пошук)")

    @task(4)
    def equipment_detail(self):
        self.client.get(f"/equipment/{random.choice(self.type_ids)}/", name="/equipment/[id]/")


class Client(HttpUser):
    weight = 3
    wait_time = between(2, 5)

    def on_start(self):
        number = (next(_client_numbers) - 1) % CLIENTS + 1
        login(self, f"loadclient{number:03d}", LOAD_PASSWORD)
        response = self.client.get("/", name="/ (каталог)")
        self.type_ids = TYPE_LINK_RE.findall(response.text) or ["1"]

    @task(4)
    def browse(self):
        self.client.get(f"/equipment/{random.choice(self.type_ids)}/", name="/equipment/[id]/")

    @task(3)
    def book(self):
        type_id = random.choice(self.type_ids)
        url = f"/bookings/new/{type_id}/"
        with self.client.get(url, name="/bookings/new/[id]/", catch_response=True) as form:
            token = csrf_token(form)
            units = UNIT_OPTION_RE.findall(form.text)
        if not units:
            return

        start = date.today() + timedelta(days=random.randint(1, 120))
        end = start + timedelta(days=random.randint(1, 5))
        with self.client.post(
            url,
            {
                "unit": random.choice(units),
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "csrfmiddlewaretoken": token,
            },
            name="/bookings/new/[id]/ [POST]",
            catch_response=True,
        ) as response:
            # Два очікувані результати: бронювання створено (перехід на сторінку заявки)
            # або період уже зайнятий (форма з поясненням). Усе інше — помилка.
            if "/bookings/new/" not in response.url:
                response.success()
            elif "уже заброньовано" in response.text:
                response.success()
                self.environment.events.request.fire(
                    request_type="INFO", name="бронювання: конфлікт дат (очікувано)",
                    response_time=0, response_length=0, exception=None, context={},
                )
            else:
                response.failure("Форма повернула неочікувану помилку")

    @task(2)
    def my_bookings(self):
        self.client.get("/bookings/my/", name="/bookings/my/")


class Manager(HttpUser):
    weight = 1
    wait_time = between(2, 5)

    def on_start(self):
        login(self, *MANAGER)

    @task(3)
    def issue_tab(self):
        self.client.get("/manage/", name="/manage/ (до видачі)")

    @task(1)
    def issued_tab(self):
        self.client.get("/manage/", params={"tab": "issued"}, name="/manage/?tab=issued")

    @task(1)
    def filtered(self):
        start = date.today() + timedelta(days=random.randint(0, 60))
        self.client.get(
            "/manage/",
            params={"from": start.isoformat(), "to": (start + timedelta(days=14)).isoformat()},
            name="/manage/?from=&to= (фільтр)",
        )
