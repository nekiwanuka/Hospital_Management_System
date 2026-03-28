from django.contrib import admin

from apps.referrals.models import Referral


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "referring_doctor",
        "facility_name",
        "referral_date",
        "branch",
    )
    list_filter = ("branch", "referral_date")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "facility_name",
        "reason",
    )
    autocomplete_fields = ("patient", "visit", "referring_doctor")
    readonly_fields = ("referral_date",)
    list_per_page = 25
    fieldsets = (
        ("Patient & Visit", {"fields": ("patient", "visit")}),
        (
            "Referral Details",
            {"fields": ("referring_doctor", "facility_name", "reason")},
        ),
        ("System", {"fields": ("branch", "referral_date")}),
    )
