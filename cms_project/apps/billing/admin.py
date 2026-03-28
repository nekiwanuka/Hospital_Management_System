from django.contrib import admin

from apps.billing.models import Invoice, InvoiceLineItem, Receipt


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "patient",
        "total_amount",
        "payment_method",
        "payment_status",
        "cashier",
        "branch",
        "date",
    )
    list_filter = ("payment_method", "payment_status", "branch", "date")
    search_fields = (
        "invoice_number",
        "patient__patient_id",
        "patient__first_name",
        "patient__last_name",
    )


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "service_type",
        "description",
        "amount",
        "branch",
    )
    list_filter = ("service_type", "branch")
    search_fields = ("invoice__invoice_number", "description", "source_model")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "invoice",
        "patient",
        "amount_paid",
        "receipt_type",
        "payment_method",
        "received_by",
        "created_at",
    )
    list_filter = ("receipt_type", "payment_method", "branch")
    search_fields = (
        "receipt_number",
        "invoice__invoice_number",
        "patient__first_name",
        "patient__last_name",
    )
