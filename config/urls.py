from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.views import register

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("register/", register, name="register"),
    path("bookings/", include("bookings.urls")),
    path("manage/", include("bookings.manager_urls")),
    path("", include("catalog.urls")),
]
