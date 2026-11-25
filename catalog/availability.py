"""Календар доступності екземпляра на місяць.

Для кожного дня визначається стан:
  busy   — день входить в активне бронювання [start_date; end_date);
  buffer — день технічної перерви [end_date; end_date + buffer_days);
  free   — вільний день;
  past   — день у минулому (бронювати не можна).
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

MONTH_NAMES = [
    "", "січень", "лютий", "березень", "квітень", "травень", "червень",
    "липень", "серпень", "вересень", "жовтень", "листопад", "грудень",
]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]


@dataclass
class Day:
    date: date
    state: str  # busy | buffer | free | past
    is_today: bool

    @property
    def title(self) -> str:
        labels = {"busy": "зайнято", "buffer": "технічна перерва", "free": "вільно", "past": "минуло"}
        return f"{self.date:%d.%m.%Y}: {labels[self.state]}"


@dataclass
class Month:
    year: int
    month: int
    weeks: list[list[Day | None]]

    @property
    def title(self) -> str:
        return f"{MONTH_NAMES[self.month]} {self.year}"


def add_months(first_day: date, months: int) -> date:
    index = first_day.year * 12 + (first_day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def day_states(bookings, start: date, end: date) -> dict[date, str]:
    """Стан кожного зайнятого дня в межах [start; end]. Вільні дні не потрапляють у словник."""
    states: dict[date, str] = {}
    for booking in bookings:
        day = max(booking.start_date, start)
        while day < min(booking.end_date, end + timedelta(days=1)):
            states[day] = "busy"
            day += timedelta(days=1)
        day = max(booking.end_date, start)
        while day < min(booking.busy_until, end + timedelta(days=1)):
            # Перерва однієї оренди може збігтися з початком іншої: «зайнято» важливіше.
            states.setdefault(day, "buffer")
            day += timedelta(days=1)
    return states


def build_month(year: int, month: int, bookings, today: date) -> Month:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    states = day_states(bookings, first, last)
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row = []
        for day in week:
            if day.month != month:
                row.append(None)
            elif day < today:
                row.append(Day(day, "past", False))
            else:
                row.append(Day(day, states.get(day, "free"), day == today))
        weeks.append(row)
    return Month(year, month, weeks)
