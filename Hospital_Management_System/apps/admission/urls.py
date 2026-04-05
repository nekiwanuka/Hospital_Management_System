from django.urls import path

from apps.admission import views

app_name = "admission"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("nurse-station/", views.nurse_station, name="nurse_station"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/discharge/", views.discharge, name="discharge"),
    path("<int:pk>/daily-charges/", views.daily_charges, name="daily_charges"),
    path(
        "<int:pk>/daily-charges/generate/",
        views.generate_daily_invoice,
        name="generate_daily_invoice",
    ),
    path(
        "<int:pk>/daily-charges/print/",
        views.print_daily_invoice,
        name="print_daily_invoice",
    ),
    path("<int:admission_pk>/notes/", views.nursing_notes, name="nursing_notes"),
    path(
        "<int:admission_pk>/notes/add/", views.add_nursing_note, name="add_nursing_note"
    ),
    path("<int:admission_pk>/vitals/", views.vitals_chart, name="vitals_chart"),
    path("<int:admission_pk>/vitals/add/", views.record_vitals, name="record_vitals"),
    # Medication administration
    path(
        "<int:admission_pk>/medications/",
        views.medication_chart,
        name="medication_chart",
    ),
    path(
        "<int:admission_pk>/medications/add/",
        views.administer_medication,
        name="administer_medication",
    ),
    # Ward rounds
    path(
        "<int:admission_pk>/rounds/",
        views.ward_rounds_list,
        name="ward_rounds",
    ),
    path(
        "<int:admission_pk>/rounds/add/",
        views.add_ward_round,
        name="add_ward_round",
    ),
    # Doctor orders
    path(
        "<int:admission_pk>/orders/",
        views.doctor_orders_list,
        name="doctor_orders",
    ),
    path(
        "<int:admission_pk>/orders/add/",
        views.add_doctor_order,
        name="add_doctor_order",
    ),
    path(
        "<int:admission_pk>/orders/<int:order_pk>/carry-out/",
        views.carry_out_order,
        name="carry_out_order",
    ),
    # Daily reports
    path(
        "<int:admission_pk>/reports/",
        views.daily_reports_list,
        name="daily_reports",
    ),
    path(
        "<int:admission_pk>/reports/add/",
        views.add_daily_report,
        name="add_daily_report",
    ),
    # Intake/Output
    path(
        "<int:admission_pk>/io/",
        views.intake_output_chart,
        name="intake_output",
    ),
    path(
        "<int:admission_pk>/io/add/",
        views.add_intake_output,
        name="add_intake_output",
    ),
    # Bed & ward management
    path("beds/", views.bed_management, name="bed_management"),
    path("beds/add/", views.bed_add, name="bed_add"),
    path("wards/", views.ward_list, name="ward_list"),
    path("wards/create/", views.ward_create, name="ward_create"),
    path("wards/<int:pk>/edit/", views.ward_edit, name="ward_edit"),
]
