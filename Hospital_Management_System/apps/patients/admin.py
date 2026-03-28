from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "patient_id",
        "first_name",
        "last_name",
        "gender",
        "date_of_birth",
        "phone",
        "blood_group",
        "branch",
        "date_registered",
    )
    list_filter = ("gender", "blood_group", "branch")
    search_fields = (
        "patient_id",
        "first_name",
        "last_name",
        "phone",
    )
    readonly_fields = ("patient_id", "date_registered")
    list_per_page = 25
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "patient_id",
                    "first_name",
                    "last_name",
                    "gender",
                    "date_of_birth",
                )
            },
        ),
        ("Contact", {"fields": ("phone", "address")}),
        ("Medical", {"fields": ("blood_group", "allergies")}),
        ("Next of Kin", {"fields": ("next_of_kin", "next_of_kin_phone")}),
        ("System", {"fields": ("branch", "date_registered")}),
    )
