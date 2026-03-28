from django.contrib import admin

from apps.laboratory.models import LabRequest


@admin.register(LabRequest)
class LabRequestAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "test_type",
        "status",
        "sample_collected",
        "requested_by",
        "technician",
        "branch",
        "date",
    )
    list_filter = ("status", "sample_collected", "branch", "date")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "test_type",
    )
