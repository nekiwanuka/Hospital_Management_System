from django.contrib import admin

from apps.admission.models import (
    Admission,
    AdmissionDailyCharge,
    Bed,
    DailyReport,
    DoctorOrder,
    IntakeOutput,
    MedicationAdministration,
    NursingNote,
    VitalSign,
    Ward,
    WardRound,
)


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "ward_type",
        "ward_category",
        "daily_rate",
        "floor",
        "is_active",
        "branch",
    )
    list_filter = ("branch", "ward_type", "ward_category", "is_active")
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


@admin.register(AdmissionDailyCharge)
class AdmissionDailyChargeAdmin(admin.ModelAdmin):
    list_display = ("admission", "charge_date", "amount", "ward_category", "branch")
    list_filter = ("branch", "ward_category", "charge_date")
    raw_id_fields = ("admission", "invoice_line")


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


@admin.register(MedicationAdministration)
class MedicationAdministrationAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "medicine_name",
        "dosage",
        "route",
        "status",
        "scheduled_time",
        "administered_by",
        "branch",
    )
    list_filter = ("status", "route", "branch")
    raw_id_fields = ("admission", "administered_by")


@admin.register(WardRound)
class WardRoundAdmin(admin.ModelAdmin):
    list_display = ("admission", "doctor", "nurse", "round_time", "branch")
    list_filter = ("branch", "round_time")
    raw_id_fields = ("admission", "doctor", "nurse")


@admin.register(DoctorOrder)
class DoctorOrderAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "ordered_by",
        "order_type",
        "priority",
        "status",
        "created_at",
        "branch",
    )
    list_filter = ("status", "priority", "order_type", "branch")
    raw_id_fields = ("admission", "ordered_by", "carried_out_by")


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "nurse",
        "report_date",
        "shift",
        "pain_level",
        "branch",
    )
    list_filter = ("shift", "branch", "report_date")
    raw_id_fields = ("admission", "nurse")


@admin.register(IntakeOutput)
class IntakeOutputAdmin(admin.ModelAdmin):
    list_display = (
        "admission",
        "entry_type",
        "amount_ml",
        "recorded_by",
        "recorded_at",
        "branch",
    )
    list_filter = ("entry_type", "branch")
    raw_id_fields = ("admission", "recorded_by")
