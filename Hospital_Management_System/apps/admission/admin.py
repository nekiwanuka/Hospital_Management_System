from django.contrib import admin

from apps.admission.models import Admission, Bed, NursingNote, VitalSign, Ward


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ("name", "ward_type", "floor", "is_active", "branch")
    list_filter = ("branch", "ward_type", "is_active")
    search_fields = ("name",)


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ("bed_number", "ward", "status", "branch")
    list_filter = ("status", "ward__branch", "ward")
    search_fields = ("bed_number", "ward__name")
    raw_id_fields = ("ward",)


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


@admin.register(VitalSign)
class VitalSignAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "temperature",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "pulse_rate",
        "oxygen_saturation",
        "recorded_by",
        "created_at",
        "branch",
    )
    list_filter = ("branch", "created_at")
    raw_id_fields = ("admission", "recorded_by")
