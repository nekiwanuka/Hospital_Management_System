from django.contrib import admin

from apps.visits.models import Visit, VisitQueueEvent


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = (
        "visit_number",
        "patient",
        "visit_type",
        "status",
        "check_in_time",
        "check_out_time",
        "branch",
    )
    list_filter = ("visit_type", "status", "branch", "check_in_time")
    search_fields = (
        "visit_number",
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
    )


@admin.register(VisitQueueEvent)
class VisitQueueEventAdmin(admin.ModelAdmin):
    list_display = (
        "visit",
        "from_status",
        "to_status",
        "moved_by",
        "moved_at",
        "branch",
    )
    list_filter = ("to_status", "branch", "moved_at")
    search_fields = ("visit__visit_number", "visit__patient__patient_id")
