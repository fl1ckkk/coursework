import re

from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User

PHONE_RE = re.compile(r"^\+?\d{10,15}$")


class RegistrationForm(UserCreationForm):
    """Реєстрація нового клієнта.

    Роль не вибирається у формі: кожен, хто реєструється сам, стає клієнтом.
    Менеджера призначає адміністратор в адмінці.
    """

    first_name = forms.CharField(label="Ім'я", max_length=150)
    last_name = forms.CharField(label="Прізвище", max_length=150)
    email = forms.EmailField(label="Електронна пошта")
    phone = forms.CharField(
        label="Телефон",
        max_length=20,
        help_text="Для зв'язку щодо видачі обладнання, наприклад +380501234567.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Користувач із такою електронною поштою вже існує.")
        return email

    def clean_phone(self):
        # Прибираємо пробіли, дужки й дефіси, які люди зазвичай вводять.
        phone = re.sub(r"[\s()\-]", "", self.cleaned_data["phone"])
        if not PHONE_RE.match(phone):
            raise forms.ValidationError("Введіть номер телефону з 10–15 цифр, наприклад +380501234567.")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CLIENT
        if commit:
            user.save()
        return user
