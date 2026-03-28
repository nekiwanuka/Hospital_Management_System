from django.contrib import admin

from apps.emergency.models import EmergencyCase


@admin.register(EmergencyCase)
class EmergencyCaseAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "emergency_level",
        "doctor",
        "date",
        "branch",
    )
    list_filter = ("emergency_level", "branch", "date")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "doctor__username",
    )
