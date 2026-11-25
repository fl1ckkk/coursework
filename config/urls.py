from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("bookings/", include("bookings.urls")),
    path("manage/", include("bookings.manager_urls")),
    path("", include("catalog.urls")),
]
