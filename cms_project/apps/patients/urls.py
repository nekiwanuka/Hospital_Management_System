from django.urls import path

from apps.patients import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
]
