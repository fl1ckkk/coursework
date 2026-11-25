from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("my/", views.my_bookings, name="my"),
    path("new/<int:type_pk>/", views.booking_create, name="create"),
    path("<int:pk>/", views.booking_detail, name="detail"),
    path("<int:pk>/cancel/", views.booking_cancel, name="cancel"),
    path("<int:pk>/extend/", views.booking_extend, name="extend"),
]
