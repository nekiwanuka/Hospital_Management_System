from django.contrib import admin

from apps.triage.models import TriageRecord


@admin.register(TriageRecord)
class TriageRecordAdmin(admin.ModelAdmin):
    list_display = (
        "visit_number",
        "patient",
        "outcome",
        "triage_officer",
        "branch",
        "date",
    )
    list_filter = ("outcome", "branch", "date")
    search_fields = (
        "visit_number",
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
    )
