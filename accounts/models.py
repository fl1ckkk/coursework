from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Користувач системи з предметною роллю.

    Роль визначає повноваження: клієнт бронює обладнання,
    менеджер погоджує заявки, видає й приймає обладнання.
    """

    class Role(models.TextChoices):
        CLIENT = "client", "Клієнт"
        MANAGER = "manager", "Менеджер"

    role = models.CharField("роль", max_length=16, choices=Role.choices, default=Role.CLIENT)
    phone = models.CharField("телефон", max_length=20, blank=True)

    @property
    def is_manager(self) -> bool:
        return self.role == self.Role.MANAGER

    def __str__(self) -> str:
        return self.get_full_name() or self.username
