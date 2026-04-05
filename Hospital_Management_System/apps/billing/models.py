from django.conf import settings
from django.db import models
from decimal import Decimal
from apps.core.models import BranchScopedModel


class Invoice(BranchScopedModel):
    PAYMENT_METHODS = [
        ("cash", "Cash"),
        ("mobile_money", "Mobile Money"),
        ("bank_transfer", "Bank Transfer"),
        ("card", "Card"),
        ("insurance", "Insurance"),
    ]
    PAYMENT_STATUS = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("partial", "Partial"),
        ("post_payment", "Post Payment"),
    ]

    invoice_number = models.CharField(max_length=40, unique=True)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True
    )
    walk_in_customer_name = models.CharField(max_length=255, blank=True)
    walk_in_customer_phone = models.CharField(max_length=50, blank=True)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    services = models.TextField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default="pending"
    )
    date = models.DateTimeField(auto_now_add=True)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["payment_status"]),
        ]

    def __str__(self):
        return self.invoice_number

    @property
    def customer_display_name(self):
        if self.patient:
            return f"{self.patient.first_name} {self.patient.last_name}"
        return self.walk_in_customer_name or "Walk-In Customer"

    @property
    def is_walk_in(self):
        return not self.patient_id and bool(self.walk_in_customer_name)

    @property
    def total_paid_amount(self):
        return self.amount_paid

    @property
    def balance_due_amount(self):
        balance = self.total_amount - self.amount_paid
        return balance if balance > 0 else Decimal("0.00")


class InvoiceLineItem(BranchScopedModel):
    SERVICE_TYPES = [
        ("consultation", "Consultation"),
        ("lab", "Lab Test"),
        ("radiology", "Radiology Scan"),
        ("pharmacy", "Pharmacy Medicine"),
        ("referral", "Referral"),
        ("admission", "Admission / Ward Charge"),
    ]
    LINE_PAYMENT_STATUS = [
        ("pending", "Pending"),
        ("partial", "Partial"),
        ("paid", "Paid"),
    ]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="line_items"
    )
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_status = models.CharField(
        max_length=20, choices=LINE_PAYMENT_STATUS, default="pending"
    )
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_deducted_at = models.DateTimeField(null=True, blank=True)
    source_model = models.CharField(max_length=40)
    source_id = models.PositiveIntegerField()

    # Cashier authorization for post-payment (credit) line items
    cashier_authorized = models.BooleanField(
        default=True,
        help_text="Whether the cashier has authorized this charge. "
        "False = pending cashier approval before the service can be provided.",
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_line_items",
    )
    authorized_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "service_type"]),
            models.Index(fields=["source_model", "source_id"]),
            models.Index(fields=["branch", "cashier_authorized"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_model", "source_id"],
                name="billing_unique_source_item",
            )
        ]

    def __str__(self):
        return f"{self.invoice.invoice_number}: {self.description}"

    @property
    def balance_due_amount(self):
        balance = self.amount - self.paid_amount
        return balance if balance > 0 else Decimal("0.00")


class CashDrawer(BranchScopedModel):
    service_type = models.CharField(
        max_length=20, choices=InvoiceLineItem.SERVICE_TYPES
    )
    drawer_name = models.CharField(max_length=120)
    assigned_cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_cash_drawers",
    )
    is_active = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "service_type"],
                name="billing_unique_branch_service_drawer",
            )
        ]
        indexes = [
            models.Index(fields=["branch", "service_type"]),
            models.Index(fields=["branch", "is_active"]),
        ]

    def __str__(self):
        return self.drawer_name


class InvoiceLinePayment(BranchScopedModel):
    line_item = models.ForeignKey(
        InvoiceLineItem,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    drawer = models.ForeignKey(
        CashDrawer,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=Invoice.PAYMENT_METHODS)
    transaction_id = models.CharField(max_length=120, blank=True)
    payer_phone = models.CharField(
        max_length=20, blank=True, help_text="Mobile money phone number"
    )
    network = models.CharField(
        max_length=20,
        blank=True,
        choices=[("mtn", "MTN"), ("airtel", "Airtel"), ("other", "Other")],
        help_text="Mobile money network",
    )
    bank_name = models.CharField(
        max_length=100, blank=True, help_text="Bank name for bank transfers"
    )
    bank_account = models.CharField(
        max_length=40, blank=True, help_text="Bank account number"
    )
    card_last_four = models.CharField(
        max_length=4, blank=True, help_text="Last 4 digits of card"
    )
    cardholder_name = models.CharField(max_length=120, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invoice_line_payments",
    )
    paid_at = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "paid_at"]),
            models.Index(fields=["branch", "drawer", "paid_at"]),
            models.Index(fields=["branch", "received_by", "paid_at"]),
        ]

    def __str__(self):
        return f"{self.line_item.invoice.invoice_number} - {self.amount_paid}"


class CashierShiftSession(BranchScopedModel):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("pending_approval", "Pending Approval"),
        ("closed", "Closed"),
    ]

    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cashier_shift_opened",
    )
    opening_float = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cashier_shift_closed",
    )
    declared_cash_total = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    expected_cash_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    variance_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    variance_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=5000,
    )
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "opened_by", "status"]),
            models.Index(fields=["branch", "status", "created_at"]),
        ]

    def __str__(self):
        return f"Shift #{self.pk} - {self.opened_by} ({self.status})"


class Receipt(BranchScopedModel):
    RECEIPT_TYPES = [
        ("full", "Full Payment"),
        ("partial", "Partial Payment"),
    ]

    receipt_number = models.CharField(max_length=40, unique=True)
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.CASCADE, related_name="receipts"
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    total_invoice_amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=Invoice.PAYMENT_METHODS)
    transaction_id = models.CharField(max_length=120, blank=True)
    receipt_type = models.CharField(
        max_length=20, choices=RECEIPT_TYPES, default="full"
    )
    service_type = models.CharField(
        max_length=40,
        blank=True,
        help_text="Service category: consultation, lab, radiology, pharmacy, referral, or mixed",
    )
    service_description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Human-readable description of services paid for",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="receipts_issued",
    )
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["invoice"]),
        ]

    def __str__(self):
        return self.receipt_number


class ApprovalRequest(BranchScopedModel):
    APPROVAL_TYPES = [
        ("paid_rollback", "Paid Status Rollback"),
        ("void_invoice", "Void Invoice"),
        ("refund", "Refund"),
        ("discount_override", "Discount Override"),
        ("reopen_day", "Reopen Day"),
        ("shift_variance", "Shift Variance Approval"),
        ("partial_payment", "Partial Payment Approval"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("cancelled", "Cancelled"),
    ]

    approval_type = models.CharField(max_length=40, choices=APPROVAL_TYPES)
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="approval_requests",
        null=True,
        blank=True,
    )
    cashier_shift = models.ForeignKey(
        "billing.CashierShiftSession",
        on_delete=models.CASCADE,
        related_name="approval_requests",
        null=True,
        blank=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_requests_made",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests_reviewed",
    )
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    requested_payment_method = models.CharField(max_length=20, blank=True)
    reason = models.TextField()
    reviewer_notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "status", "created_at"]),
            models.Index(fields=["approval_type", "status", "created_at"]),
        ]

    def __str__(self):
        target = self.invoice.invoice_number if self.invoice else "N/A"
        return f"{self.get_approval_type_display()} - {target} ({self.status})"


class FinancialSequenceAnomaly(BranchScopedModel):
    ANOMALY_TYPES = [
        ("duplicate_sequence", "Duplicate Sequence"),
        ("missing_sequence", "Missing Sequence"),
        ("invalid_format", "Invalid Format"),
    ]
    OBJECT_TYPES = [
        ("invoice", "Invoice"),
        ("receipt", "Receipt"),
    ]
    SEVERITIES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    anomaly_date = models.DateField()
    anomaly_type = models.CharField(max_length=30, choices=ANOMALY_TYPES)
    object_type = models.CharField(max_length=20, choices=OBJECT_TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITIES, default="medium")
    message = models.TextField()
    reference_value = models.CharField(max_length=120, blank=True)
    is_resolved = models.BooleanField(default=False)
    detected_by = models.CharField(max_length=80, default="sequence-check-command")

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "anomaly_date", "is_resolved"]),
            models.Index(fields=["object_type", "anomaly_type", "anomaly_date"]),
        ]

    def __str__(self):
        return f"{self.object_type}:{self.anomaly_type} ({self.anomaly_date})"
