from django.urls import path
from apps.core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/director/", views.director_dashboard, name="director_dashboard"),
    path(
        "dashboard/system-admin/",
        views.system_admin_dashboard,
        name="system_admin_dashboard",
    ),
    path("help/", views.help_manuals, name="help"),
    path("setup/", views.setup_redirect, name="setup"),
    path("delete-request/", views.request_delete, name="request_delete"),
    path("delete-requests/", views.delete_requests_list, name="delete_requests"),
    path(
        "delete-requests/<int:pk>/review/",
        views.review_delete_request,
        name="review_delete_request",
    ),
]
