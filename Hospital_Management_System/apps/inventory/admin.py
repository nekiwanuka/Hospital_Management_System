from django.contrib import admin

from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    Dispense,
    DispenseItem,
    InventoryStoreProfile,
    Item,
    StockIssue,
    StockItem,
    StockMovement,
    StockReturn,
    Supplier,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "created_at")
    search_fields = ("name",)
    list_filter = ("branch",)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "manufacturer", "country", "branch")
    search_fields = ("name", "manufacturer")
    list_filter = ("branch", "country")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "branch")
    search_fields = ("name", "contact")
    list_filter = ("branch",)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "item_name",
        "generic_name",
        "category",
        "brand",
        "store_department",
        "reorder_level",
        "is_active",
        "branch",
    )
    search_fields = ("item_name", "generic_name", "barcode")
    list_filter = ("branch", "store_department", "category", "brand", "is_active")


@admin.register(InventoryStoreProfile)
class InventoryStoreProfileAdmin(admin.ModelAdmin):
    list_display = ("store_department", "manager", "location", "branch")
    search_fields = (
        "location",
        "manager__username",
        "manager__first_name",
        "manager__last_name",
    )
    list_filter = ("branch", "store_department")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "batch_number",
        "exp_date",
        "quantity_received",
        "quantity_remaining",
        "unit_cost",
        "selling_price_per_unit",
        "profit_margin",
        "branch",
    )
    search_fields = ("item__item_name", "batch_number", "barcode")
    list_filter = ("branch", "exp_date")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("item", "batch", "movement_type", "quantity", "date", "branch")
    search_fields = ("item__item_name", "batch__batch_number", "reference")
    list_filter = ("branch", "movement_type", "date")


@admin.register(Dispense)
class DispenseAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "total_amount", "dispensed_by", "date", "branch")
    search_fields = ("patient__patient_id", "patient__first_name", "patient__last_name")
    list_filter = ("branch", "date")


@admin.register(DispenseItem)
class DispenseItemAdmin(admin.ModelAdmin):
    list_display = (
        "dispense",
        "item",
        "batch",
        "quantity",
        "unit_price",
        "total_price",
        "branch",
    )
    search_fields = ("item__item_name", "batch__batch_number")
    list_filter = ("branch",)


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = (
        "item_name",
        "department",
        "quantity",
        "stock_rate",
        "charge_rate",
        "branch",
    )
    search_fields = ("item_name", "category", "service_code")
    list_filter = ("branch", "department", "service_type", "is_active")


@admin.register(StockIssue)
class StockIssueAdmin(admin.ModelAdmin):
    list_display = (
        "stock_item",
        "issued_to",
        "quantity",
        "total_cost",
        "issued_by",
        "created_at",
        "branch",
    )
    search_fields = ("stock_item__item_name", "notes")
    list_filter = ("branch", "issued_to", "created_at")


@admin.register(StockReturn)
class StockReturnAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "quantity",
        "return_source",
        "status",
        "returned_by",
        "verified_by",
        "created_at",
        "branch",
    )
    search_fields = ("item__item_name", "reason")
    list_filter = ("branch", "status", "return_source", "created_at")
