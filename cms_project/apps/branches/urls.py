from django.urls import path

from apps.branches import views

app_name = "branches"

urlpatterns = [
    path("", views.index, name="index"),
]
