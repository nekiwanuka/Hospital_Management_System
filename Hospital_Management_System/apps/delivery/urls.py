from django.urls import path

from apps.delivery import views

app_name = "delivery"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/outcome/", views.record_outcome, name="record_outcome"),
    path("<int:pk>/status/", views.update_status, name="update_status"),
    path("<int:pk>/discharge/", views.discharge, name="discharge"),
    path("<int:pk>/note/", views.add_note, name="add_note"),
]
