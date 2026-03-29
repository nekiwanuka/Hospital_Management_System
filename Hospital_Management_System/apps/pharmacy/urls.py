from django.urls import path

from apps.pharmacy import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.index, name="index"),
    path("medicine/new/", views.create_medicine, name="create_medicine"),
    path("dispense/", views.dispense, name="dispense"),
    path("dispense/walkin/", views.dispense_walkin, name="dispense_walkin"),
    path(
        "dispense/prescription/",
        views.dispense_prescription,
        name="dispense_prescription",
    ),
    path("prescriptions/", views.prescriptions, name="prescriptions"),
    path("receipts/", views.pharmacy_receipts, name="pharmacy_receipts"),
]
