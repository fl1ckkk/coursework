from django.urls import path

from . import manager_views

app_name = "manage"

urlpatterns = [
    path("", manager_views.manage_list, name="list"),
    path("<int:pk>/<slug:action>/", manager_views.manage_action, name="action"),
]
