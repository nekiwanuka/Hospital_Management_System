from django.contrib import admin

from apps.delivery.models import DeliveryRecord, DeliveryNote


@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "status",
        "delivery_type",
        "outcome",
        "delivered_by",
        "admitted_at",
        "delivery_datetime",
        "branch",
    )
    list_filter = ("branch", "status", "delivery_type", "outcome")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__patient_id",
    )
    raw_id_fields = ("patient", "visit", "admission", "delivered_by", "midwife")


@admin.register(DeliveryNote)
class DeliveryNoteAdmin(admin.ModelAdmin):
    list_display = ("delivery", "author", "category", "created_at", "branch")
    list_filter = ("category", "branch", "created_at")
    search_fields = ("note",)
    raw_id_fields = ("delivery", "author")
