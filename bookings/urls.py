from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("new/<int:type_pk>/", views.booking_create, name="create"),
    path("<int:pk>/", views.booking_detail, name="detail"),
]
