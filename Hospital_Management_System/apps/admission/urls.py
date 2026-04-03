from django.urls import path

from apps.admission import views

app_name = "admission"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
    path("nurse-station/", views.nurse_station, name="nurse_station"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/discharge/", views.discharge, name="discharge"),
    path("<int:admission_pk>/notes/", views.nursing_notes, name="nursing_notes"),
    path(
        "<int:admission_pk>/notes/add/", views.add_nursing_note, name="add_nursing_note"
    ),
    path("<int:admission_pk>/vitals/", views.vitals_chart, name="vitals_chart"),
    path("<int:admission_pk>/vitals/add/", views.record_vitals, name="record_vitals"),
    path("beds/", views.bed_management, name="bed_management"),
]
