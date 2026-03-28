from django.urls import path

from .views import (
    ClinicLoginView,
    ClinicLogoutView,
    create_user,
    edit_user,
    users_index,
)

app_name = "accounts"

urlpatterns = [
    path("login/", ClinicLoginView.as_view(), name="login"),
    path("logout/", ClinicLogoutView.as_view(), name="logout"),
    path("", users_index, name="index"),
    path("create/", create_user, name="create"),
    path("<int:pk>/edit/", edit_user, name="edit"),
]
