from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import RegistrationForm


def register(request):
    """Реєстрація клієнта. Після успіху користувач одразу входить у систему."""
    if request.user.is_authenticated:
        return redirect("catalog:list")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Вітаємо, {user.first_name}! Реєстрацію завершено.")
            return redirect("catalog:list")
    else:
        form = RegistrationForm()
    return render(request, "registration/register.html", {"form": form})
