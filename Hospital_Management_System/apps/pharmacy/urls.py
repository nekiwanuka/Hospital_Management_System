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
    path(
        "receipts/<int:receipt_pk>/",
        views.pharmacy_receipt_detail,
        name="pharmacy_receipt_detail",
    ),
    path("transfers/", views.pharmacy_transfer_report, name="transfer_report"),
    # Walk-in status (read-only) & dispensing cleared sales
    path("walkins/", views.pending_walkins, name="pending_walkins"),
    path(
        "walkins/<int:sale_pk>/dispense/",
        views.dispense_walkin_cleared,
        name="dispense_walkin_cleared",
    ),
    # Shift management
    path("shifts/open/", views.open_shift, name="open_shift"),
    path("shifts/<int:shift_pk>/close/", views.close_shift, name="close_shift"),
    path("shifts/<int:shift_pk>/report/", views.shift_report, name="shift_report"),
    path("shifts/", views.shift_history, name="shift_history"),
]
