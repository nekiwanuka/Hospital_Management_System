from django.contrib import admin

from apps.admission.models import Admission, NursingNote


@admin.register(NursingNote)
class NursingNoteAdmin(admin.ModelAdmin):
    list_display = ("admission", "nurse", "category", "created_at", "branch")
    list_filter = ("category", "branch", "created_at")
    search_fields = (
        "admission__patient__first_name",
        "admission__patient__last_name",
        "note",
    )
    raw_id_fields = ("admission", "nurse")


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "ward",
        "bed",
        "doctor",
        "nurse",
        "admission_date",
        "discharge_date",
        "branch",
    )
    list_filter = ("branch", "ward", "admission_date", "discharge_date")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "ward",
        "bed",
    )
