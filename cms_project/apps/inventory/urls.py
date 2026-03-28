from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "medical-store/dashboard/",
        views.medical_store_dashboard,
        name="medical_store_dashboard",
    ),
    path(
        "medical-store/dashboard/<str:store>/",
        views.medical_store_dashboard,
        name="medical_store_dashboard_by_store",
    ),
    path("create/", views.create_item, name="create"),
    path("medical-store/entry/", views.medical_store_entry, name="medical_store_entry"),
    path(
        "medical-store/<str:store>/entry/",
        views.medical_store_entry,
        name="medical_store_entry_by_store",
    ),
    path("issue/", views.issue_stock, name="issue"),
    path(
        "pharmacy-requests/<int:pk>/fulfill/",
        views.fulfill_pharmacy_request,
        name="fulfill_pharmacy_request",
    ),
    path(
        "store-requests/<int:pk>/<str:action>/",
        views.update_store_request_status,
        name="update_store_request_status",
    ),
]
