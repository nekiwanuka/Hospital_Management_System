from django.urls import path

from apps.patients import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("check-duplicate/", views.check_duplicate, name="check_duplicate"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/documents/upload/", views.upload_document, name="upload_document"),
    path(
        "<int:pk>/documents/<int:doc_pk>/delete/",
        views.delete_document,
        name="delete_document",
    ),
]
