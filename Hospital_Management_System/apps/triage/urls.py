from django.urls import path

from apps.triage import views

app_name = "triage"

urlpatterns = [
    path("", views.index, name="index"),
    path("record/", views.create, name="create"),
    path("<int:pk>/edit/", views.edit, name="edit"),
]
