from django.contrib import admin

from apps.reports.models import GeneratedReport


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = (
        "report_type",
        "export_format",
        "date_from",
        "date_to",
        "row_count",
        "generated_by",
        "branch",
        "generated_at",
    )
    list_filter = ("report_type", "export_format", "branch", "generated_at")
    search_fields = ("report_type", "generated_by__username", "branch__branch_name")
