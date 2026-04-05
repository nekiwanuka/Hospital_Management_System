from django.urls import path

from .views import (
    ClinicLoginView,
    ClinicLogoutView,
    create_user,
    edit_user,
    toggle_user_status,
    users_index,
    open_shift,
    close_shift,
    shift_history,
    manage_secret_codes,
    switch_branch,
)

app_name = "accounts"

urlpatterns = [
    path("login/", ClinicLoginView.as_view(), name="login"),
    path("logout/", ClinicLogoutView.as_view(), name="logout"),
    path("", users_index, name="index"),
    path("create/", create_user, name="create"),
    path("<int:pk>/edit/", edit_user, name="edit"),
    path("<int:pk>/toggle-status/", toggle_user_status, name="toggle_status"),
    # Shift management
    path("shift/open/", open_shift, name="open_shift"),
    path("shift/close/", close_shift, name="close_shift"),
    path("shift/history/", shift_history, name="shift_history"),
    path("shift/secret-codes/", manage_secret_codes, name="manage_secret_codes"),
    # Branch switching (director / system admin)
    path("switch-branch/", switch_branch, name="switch_branch"),
]
