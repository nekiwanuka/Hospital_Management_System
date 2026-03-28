from django.urls import path
from apps.settingsapp import views

app_name = "settingsapp"

urlpatterns = [
    path("", views.index, name="index"),
    path("edit/", views.edit_settings, name="edit_settings"),
    path("install/", views.install_wizard, name="install"),
]
