from django.urls import path

from apps.branches import views

app_name = "branches"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create_branch, name="create"),
    path("<int:pk>/edit/", views.edit_branch, name="edit"),
]
