from django.urls import path

from apps.permissions import views

app_name = "permissions"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("<int:pk>/edit/", views.update, name="update"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/toggle/", views.toggle_permission, name="toggle"),
    path("request-access/", views.request_access, name="request_access"),
    path("access-requests/", views.access_requests_list, name="access_requests"),
    path(
        "access-requests/<int:pk>/review/",
        views.review_access_request,
        name="review_access_request",
    ),
]
