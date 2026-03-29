from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db import models
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from apps.core.models import BranchScopedModel


class StockItem(BranchScopedModel):
    DEPARTMENT_CHOICES = [
        ("medical_store", "Medical Store"),
        ("laboratory", "Laboratory Materials"),
        ("radiology", "Radiology Materials"),
        ("pharmacy", "Pharmacy"),
        ("general", "General"),
    ]

    SERVICE_TYPE_CHOICES = [
        ("", "Not billable item"),
        ("lab", "Laboratory Service"),
        ("radiology", "Radiology Service"),
        ("consultation", "Consultation"),
    ]

    item_name = models.CharField(max_length=255)
    category = models.CharField(max_length=120)
    service_code = models.CharField(max_length=120, blank=True)
    service_type = models.CharField(
        max_length=20,
        choices=SERVICE_TYPE_CHOICES,
        blank=True,
        default="",
    )
    department = models.CharField(
        max_length=30, choices=DEPARTMENT_CHOICES, default="general"
    )
    quantity = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=10)
    stock_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    charge_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    is_active = models.BooleanField(default=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "item_name"]),
            models.Index(fields=["branch", "department"]),
            models.Index(fields=["branch", "service_type", "service_code"]),
        ]

    @property
    def expected_profit_per_unit(self):
        return self.charge_rate - self.stock_rate


class StockIssue(BranchScopedModel):
    TARGET_DEPARTMENT_CHOICES = [
        ("laboratory", "Laboratory"),
        ("radiology", "Radiology"),
        ("pharmacy", "Pharmacy"),
        ("general", "General"),
    ]

    stock_item = models.ForeignKey(
        StockItem,
        on_delete=models.PROTECT,
        related_name="issues",
    )
    issued_to = models.CharField(max_length=30, choices=TARGET_DEPARTMENT_CHOICES)
    quantity = models.PositiveIntegerField()
    unit_cost_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    issued_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "issued_to", "created_at"]),
            models.Index(fields=["stock_item", "created_at"]),
        ]

    def __str__(self):
        return f"{self.stock_item.item_name} x{self.quantity} -> {self.get_issued_to_display()}"


class Category(BranchScopedModel):
    name = models.CharField(max_length=120)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="inventory_unique_category_per_branch",
            )
        ]

    def __str__(self):
        return self.name


class Brand(BranchScopedModel):
    name = models.CharField(max_length=120)
    manufacturer = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="inventory_unique_brand_per_branch",
            )
        ]

    def __str__(self):
        return self.name


class Supplier(BranchScopedModel):
    name = models.CharField(max_length=180)
    contact = models.CharField(max_length=120, blank=True)
    address = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "name"],
                name="inventory_unique_supplier_per_branch",
            )
        ]

    def __str__(self):
        return self.name


class Item(BranchScopedModel):
    STORE_DEPARTMENT_CHOICES = [
        ("pharmacy", "Pharmacy Store"),
        ("laboratory", "Laboratory Store"),
        ("xray", "X-Ray Store"),
        ("ultrasound", "Ultrasound Store"),
        ("radiology", "Radiology Store"),
        ("general", "General Store"),
    ]

    SERVICE_TYPE_CHOICES = [
        ("", "Not billable item"),
        ("lab", "Laboratory Service"),
        ("radiology", "Radiology Service"),
        ("consultation", "Consultation"),
    ]

    DOSAGE_FORM_CHOICES = [
        ("tablet", "Tablet"),
        ("syrup", "Syrup"),
        ("injection", "Injection"),
        ("cream", "Cream"),
        ("capsule", "Capsule"),
        ("drops", "Drops"),
        ("other", "Other"),
    ]

    item_name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT)
    dosage_form = models.CharField(max_length=30, choices=DOSAGE_FORM_CHOICES)
    strength = models.CharField(max_length=120, blank=True)
    unit_of_measure = models.CharField(max_length=60)
    pack_size = models.CharField(max_length=60, blank=True)
    barcode = models.CharField(max_length=120, blank=True)
    store_department = models.CharField(
        max_length=30,
        choices=STORE_DEPARTMENT_CHOICES,
        default="pharmacy",
    )
    service_code = models.CharField(max_length=120, blank=True)
    service_type = models.CharField(
        max_length=20,
        choices=SERVICE_TYPE_CHOICES,
        blank=True,
        default="",
    )
    reorder_level = models.PositiveIntegerField(default=10)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    default_pack_size_units = models.PositiveIntegerField(default=1)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "item_name"]),
            models.Index(fields=["branch", "generic_name"]),
            models.Index(fields=["branch", "barcode"]),
            models.Index(fields=["branch", "is_active"]),
            models.Index(fields=["branch", "store_department"]),
            models.Index(fields=["branch", "service_type", "service_code"]),
        ]

    def __str__(self):
        return self.item_name

    @property
    def quantity_on_hand(self):
        return self.batches.aggregate(total=Coalesce(Sum("quantity_remaining"), 0))[
            "total"
        ]

    @property
    def is_low_stock(self):
        return self.quantity_on_hand <= self.reorder_level

    @property
    def mapped_department(self):
        mapping = {
            "lab": "laboratory",
            "radiology": "radiology",
            "xray": "radiology",
            "ultrasound": "radiology",
            "consultation": "consultation",
        }
        return mapping.get(self.service_type, self.store_department or "medical_store")


class InventoryStoreProfile(BranchScopedModel):
    store_department = models.CharField(
        max_length=30,
        choices=Item.STORE_DEPARTMENT_CHOICES,
    )
    manager = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_inventory_stores",
    )
    location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "store_department"])]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "store_department"],
                name="inventory_unique_store_profile_per_branch",
            )
        ]

    def clean(self):
        super().clean()
        if self.manager_id and self.manager.branch_id != self.branch_id:
            raise ValidationError(
                {"manager": "Store manager must belong to the same branch."}
            )

    @property
    def store_label(self):
        return dict(Item.STORE_DEPARTMENT_CHOICES).get(
            self.store_department,
            self.store_department,
        )

    def __str__(self):
        return f"{self.branch} - {self.store_label}"


class Batch(BranchScopedModel):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="batches")
    batch_number = models.CharField(max_length=120)
    mfg_date = models.DateField(null=True, blank=True)
    exp_date = models.DateField()
    pack_size_units = models.PositiveIntegerField(default=1)
    packs_received = models.PositiveIntegerField(default=1)
    quantity_received = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField(default=0)
    purchase_price_per_pack = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    purchase_price_total = models.DecimalField(max_digits=14, decimal_places=2)
    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    wholesale_price_per_pack = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    selling_price_per_unit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    target_margin = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("25.00"),
        help_text="Target profit margin percentage used to auto-calculate selling price.",
    )
    profit_margin = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="batches",
    )
    barcode = models.CharField(max_length=120, blank=True)
    weight = models.CharField(max_length=60, blank=True)
    volume = models.CharField(max_length=60, blank=True)
    date_received = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="inventory_batches_created",
    )

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "item", "exp_date"]),
            models.Index(fields=["branch", "exp_date"]),
            models.Index(fields=["branch", "quantity_remaining"]),
            models.Index(fields=["branch", "batch_number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "item", "batch_number"],
                name="inventory_unique_batch_per_item_per_branch",
            )
        ]

    def __str__(self):
        return f"{self.item.item_name} - {self.batch_number}"

    @property
    def is_expired(self):
        return self.exp_date < timezone.localdate()

    def _normalize_pack_pricing_fields(self):
        if self.pack_size_units <= 0:
            self.pack_size_units = 1

        # Backward compatibility for legacy callers that still send only
        # quantity_received + purchase_price_total + selling_price_per_unit.
        if self.packs_received <= 0 and self.quantity_received > 0:
            self.packs_received = max(
                self.quantity_received // self.pack_size_units,
                1,
            )

        if self.packs_received == 1 and self.quantity_received > self.pack_size_units:
            self.packs_received = max(
                self.quantity_received // self.pack_size_units,
                1,
            )

        if self.purchase_price_per_pack <= 0 and self.purchase_price_total > 0:
            self.purchase_price_per_pack = self.purchase_price_total / Decimal(
                self.packs_received
            )

    @property
    def retail_price_per_unit(self):
        return self.selling_price_per_unit

    @property
    def profit_per_unit(self):
        return self.selling_price_per_unit - self.unit_cost

    @property
    def expected_total_profit(self):
        return self.profit_per_unit * Decimal(self.quantity_remaining)

    @property
    def equivalent_packs_remaining(self):
        if self.pack_size_units <= 0:
            return Decimal("0")
        return Decimal(self.quantity_remaining) / Decimal(self.pack_size_units)

    def clean(self):
        super().clean()
        self._normalize_pack_pricing_fields()
        today = timezone.localdate()
        if self.exp_date <= today:
            raise ValidationError({"exp_date": "No expired stock entry is allowed."})
        if self.pack_size_units <= 0:
            raise ValidationError(
                {"pack_size_units": "Pack size must be greater than zero."}
            )
        if self.packs_received <= 0:
            raise ValidationError(
                {"packs_received": "Packs received must be positive."}
            )
        if self.purchase_price_per_pack <= 0:
            raise ValidationError(
                {"purchase_price_per_pack": "Purchase price per pack must be positive."}
            )
        if self.target_margin < 0 or self.target_margin >= 100:
            raise ValidationError(
                {"target_margin": "Margin must be between 0% and 99.99%."}
            )

        if self.quantity_received <= 0:
            raise ValidationError(
                {"quantity_received": "Total units received must be positive."}
            )
        if self.purchase_price_total <= 0:
            raise ValidationError(
                {"purchase_price_total": "Purchase price total must be positive."}
            )

    def save(self, *args, **kwargs):
        self._normalize_pack_pricing_fields()

        self.quantity_received = self.packs_received * self.pack_size_units
        self.purchase_price_total = (
            Decimal(self.packs_received) * self.purchase_price_per_pack
        )
        self.unit_cost = (
            self.purchase_price_per_pack / Decimal(self.pack_size_units)
        ).quantize(Decimal("0.0001"))

        # Auto-calculate selling price from target margin
        if self.target_margin > 0 and self.unit_cost > 0:
            divisor = Decimal("1.00") - self.target_margin / Decimal("100")
            self.selling_price_per_unit = (self.unit_cost / divisor).quantize(
                Decimal("0.01")
            )
        elif self.unit_cost > 0 and self.selling_price_per_unit <= 0:
            self.selling_price_per_unit = self.unit_cost

        # Auto-derive wholesale from selling price (pack-level equivalent)
        self.wholesale_price_per_pack = (
            self.selling_price_per_unit * Decimal(self.pack_size_units)
        ).quantize(Decimal("0.01"))

        # Store realised profit margin
        if self.unit_cost > 0:
            margin = (
                (self.selling_price_per_unit - self.unit_cost) / self.unit_cost
            ) * 100
            self.profit_margin = margin.quantize(Decimal("0.01"))
        else:
            self.profit_margin = Decimal("0.00")

        if not self.pk and not self.quantity_remaining:
            self.quantity_remaining = self.quantity_received

        self.full_clean()
        super().save(*args, **kwargs)

        if self.item_id and self.item.default_pack_size_units != self.pack_size_units:
            Item.objects.filter(pk=self.item_id).update(
                default_pack_size_units=self.pack_size_units
            )


class StockMovement(BranchScopedModel):
    MOVEMENT_CHOICES = [
        ("IN", "IN"),
        ("OUT", "OUT"),
        ("ADJUSTMENT", "ADJUSTMENT"),
        ("EXPIRED", "EXPIRED"),
        ("TRANSFER_OUT", "TRANSFER_OUT"),
        ("TRANSFER_IN", "TRANSFER_IN"),
    ]

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="movements",
        null=True,
        blank=True,
    )
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    quantity = models.PositiveIntegerField()
    reference = models.CharField(max_length=180, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="inventory_movements",
    )

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "movement_type", "date"]),
            models.Index(fields=["branch", "item", "date"]),
        ]

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive."})


class ServiceConsumption(BranchScopedModel):
    SERVICE_TYPE_CHOICES = [
        ("consultation", "Consultation"),
        ("lab", "Laboratory Service"),
        ("radiology", "Radiology Service"),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="service_consumptions",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="service_consumptions",
    )
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPE_CHOICES)
    service_code = models.CharField(max_length=120)
    source_model = models.CharField(max_length=40)
    source_id = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()
    unit_cost_snapshot = models.DecimalField(max_digits=14, decimal_places=4)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=180, blank=True)
    consumed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="service_consumptions",
    )
    consumed_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_service_consumptions",
    )
    reversal_reason = models.TextField(blank=True)
    reversal_reference = models.CharField(max_length=180, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "service_type", "consumed_at"]),
            models.Index(fields=["branch", "source_model", "source_id"]),
            models.Index(fields=["branch", "item", "consumed_at"]),
            models.Index(fields=["branch", "batch", "consumed_at"]),
            models.Index(fields=["branch", "reversed_at"]),
        ]

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive."})


class Dispense(BranchScopedModel):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    date = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=180, blank=True)
    dispensed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="inventory_dispenses",
    )

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "date"])]

    def __str__(self):
        return f"Dispense #{self.pk}"

    def refresh_total_amount(self):
        self.total_amount = self.items.aggregate(
            total=Coalesce(Sum("total_price"), Decimal("0.00"))
        )["total"]
        self.save(update_fields=["total_amount", "updated_at"])


class DispenseItem(BranchScopedModel):
    dispense = models.ForeignKey(
        Dispense, on_delete=models.CASCADE, related_name="items"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    total_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "item"]),
            models.Index(fields=["branch", "batch"]),
        ]

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be positive."})

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        self.full_clean()
        super().save(*args, **kwargs)


class StockTransfer(BranchScopedModel):
    """Audit record for stock transferred between stores (e.g. medical store → pharmacy)."""

    store_request = models.ForeignKey(
        "pharmacy.MedicalStoreRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_transfers",
    )
    source_item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="transfers_out",
    )
    source_batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="transfers_out",
    )
    destination_item = models.ForeignKey(
        Item,
        on_delete=models.PROTECT,
        related_name="transfers_in",
    )
    destination_batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="transfers_in",
    )
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    selling_price_per_unit = models.DecimalField(max_digits=14, decimal_places=2)
    transferred_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="stock_transfers",
    )
    transferred_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "transferred_at"]),
            models.Index(fields=["branch", "source_item"]),
            models.Index(fields=["branch", "destination_item"]),
        ]

    def __str__(self):
        return f"Transfer {self.source_item.item_name} x{self.quantity} → {self.destination_item.store_department}"
