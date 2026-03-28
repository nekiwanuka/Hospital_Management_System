from django.contrib import admin

from apps.pharmacy.models import (
    DispenseBatchAllocation,
    DispenseRecord,
    MedicalStoreRequest,
    Medicine,
    PharmacyRequest,
)


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "manufacturer",
        "batch_number",
        "expiry_date",
        "stock_quantity",
        "branch",
    )
    list_filter = ("category", "branch", "expiry_date")
    search_fields = ("name", "batch_number", "manufacturer")


@admin.register(DispenseRecord)
class DispenseRecordAdmin(admin.ModelAdmin):
    list_display = (
        "sale_type",
        "patient",
        "walk_in_name",
        "walk_in_phone",
        "medicine",
        "quantity",
        "unit_price",
        "total_cost_snapshot",
        "profit_amount",
        "prescribed_by",
        "dispensed_by",
        "dispensed_at",
        "branch",
    )
    list_filter = ("branch", "dispensed_at")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "walk_in_name",
        "walk_in_phone",
        "medicine__name",
    )


@admin.register(DispenseBatchAllocation)
class DispenseBatchAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "dispense_record",
        "item",
        "batch",
        "quantity",
        "unit_cost_snapshot",
        "total_cost",
        "total_amount",
        "branch",
    )
    list_filter = ("branch", "created_at")
    search_fields = (
        "dispense_record__id",
        "item__item_name",
        "batch__batch_number",
    )


@admin.register(MedicalStoreRequest)
class MedicalStoreRequestAdmin(admin.ModelAdmin):
    list_display = (
        "medicine_name",
        "quantity_requested",
        "status",
        "requested_by",
        "handled_by",
        "decision_remarks",
        "branch",
        "created_at",
    )
    list_filter = ("status", "branch", "created_at")
    search_fields = (
        "medicine_name",
        "category",
        "requested_by__username",
        "decision_remarks",
    )


@admin.register(PharmacyRequest)
class PharmacyRequestAdmin(admin.ModelAdmin):
    list_display = (
        "patient",
        "visit",
        "medicine",
        "quantity",
        "status",
        "requested_by",
        "branch",
        "date_requested",
    )
    list_filter = ("status", "branch", "date_requested")
    search_fields = (
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
        "medicine__name",
        "requested_by__username",
    )
