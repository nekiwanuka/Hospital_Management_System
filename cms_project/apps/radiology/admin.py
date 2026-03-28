from django.contrib import admin

from apps.radiology.models import (
    ImagingRequest,
    ImagingResult,
    RadiologyComparison,
    RadiologyImage,
    RadiologyNotification,
    RadiologyQueue,
    RadiologyType,
)


@admin.register(ImagingRequest)
class ImagingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "request_identifier",
        "patient",
        "imaging_type",
        "specific_examination",
        "priority",
        "status",
        "requested_by",
        "branch",
        "date_requested",
    )
    list_filter = ("imaging_type", "priority", "status", "branch", "date_requested")
    search_fields = (
        "request_identifier",
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "requested_by__username",
    )


@admin.register(ImagingResult)
class ImagingResultAdmin(admin.ModelAdmin):
    list_display = (
        "imaging_request",
        "machine_used",
        "technician",
        "radiologist",
        "date_performed",
        "date_reported",
        "branch",
    )
    list_filter = ("branch", "date_performed", "date_reported")
    search_fields = (
        "imaging_request__patient__patient_id",
        "imaging_request__patient__first_name",
        "imaging_request__patient__last_name",
    )


@admin.register(RadiologyType)
class RadiologyTypeAdmin(admin.ModelAdmin):
    list_display = (
        "examination_name",
        "imaging_type",
        "body_region",
        "is_active",
        "branch",
    )
    list_filter = ("imaging_type", "body_region", "is_active", "branch")
    search_fields = ("examination_name", "examination_code", "body_region")


@admin.register(RadiologyQueue)
class RadiologyQueueAdmin(admin.ModelAdmin):
    list_display = (
        "imaging_request",
        "status",
        "assigned_staff",
        "scheduled_for",
        "completed_at",
        "branch",
    )
    list_filter = ("status", "branch")
    search_fields = (
        "imaging_request__request_identifier",
        "imaging_request__patient__patient_id",
        "imaging_request__patient__first_name",
        "imaging_request__patient__last_name",
    )


@admin.register(RadiologyImage)
class RadiologyImageAdmin(admin.ModelAdmin):
    list_display = (
        "imaging_request",
        "file_kind",
        "uploaded_by",
        "upload_date",
        "branch",
    )
    list_filter = ("file_kind", "branch", "upload_date")
    search_fields = ("imaging_request__request_identifier", "caption")


@admin.register(RadiologyComparison)
class RadiologyComparisonAdmin(admin.ModelAdmin):
    list_display = (
        "current_request",
        "previous_request",
        "compared_by",
        "created_at",
        "branch",
    )
    list_filter = ("branch", "created_at")
    search_fields = (
        "current_request__request_identifier",
        "previous_request__request_identifier",
    )


@admin.register(RadiologyNotification)
class RadiologyNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "imaging_request",
        "recipient",
        "event_type",
        "is_read",
        "created_at",
        "branch",
    )
    list_filter = ("event_type", "is_read", "branch", "created_at")
    search_fields = (
        "imaging_request__request_identifier",
        "recipient__username",
        "message",
    )
