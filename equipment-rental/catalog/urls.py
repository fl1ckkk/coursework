from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.equipment_list, name="list"),
    path("equipment/<int:pk>/", views.equipment_detail, name="detail"),
]
