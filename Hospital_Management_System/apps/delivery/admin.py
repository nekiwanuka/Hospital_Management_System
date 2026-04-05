from django.contrib import admin

from apps.delivery.models import DeliveryRecord, DeliveryNote, BabyRecord


class BabyRecordInline(admin.TabularInline):
    model = BabyRecord
    extra = 1
    fields = (
        "birth_order",
        "baby_name",
        "gender",
        "weight_kg",
        "apgar_score_1min",
        "apgar_score_5min",
        "outcome",
        "resuscitation_needed",
    )


@admin.register(DeliveryRecord)
class DeliveryRecordAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "status",
        "delivery_type",
        "delivered_by",
        "admitted_at",
        "delivery_datetime",
        "branch",
    )
    list_filter = ("branch", "status", "delivery_type")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "patient__patient_id",
    )
    raw_id_fields = ("patient", "visit", "admission", "delivered_by", "midwife")
    inlines = [BabyRecordInline]


@admin.register(BabyRecord)
class BabyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "delivery",
        "birth_order",
        "baby_name",
        "gender",
        "weight_kg",
        "outcome",
        "branch",
    )
    list_filter = ("gender", "outcome", "branch")
    search_fields = (
        "baby_name",
        "delivery__patient__first_name",
        "delivery__patient__last_name",
    )
    raw_id_fields = ("delivery",)


@admin.register(DeliveryNote)
class DeliveryNoteAdmin(admin.ModelAdmin):
    list_display = ("delivery", "author", "category", "created_at", "branch")
    list_filter = ("category", "branch", "created_at")
    search_fields = ("note",)
    raw_id_fields = ("delivery", "author")
