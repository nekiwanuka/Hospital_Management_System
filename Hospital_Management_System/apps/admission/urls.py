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
    path("beds/", views.bed_management, name="bed_management"),
    path("beds/add/", views.bed_add, name="bed_add"),
    path("wards/", views.ward_list, name="ward_list"),
    path("wards/create/", views.ward_create, name="ward_create"),
    path("wards/<int:pk>/edit/", views.ward_edit, name="ward_edit"),
]
