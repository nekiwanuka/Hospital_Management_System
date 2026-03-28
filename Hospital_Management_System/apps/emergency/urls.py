from django.urls import path

from apps.emergency import views

app_name = "emergency"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
]
