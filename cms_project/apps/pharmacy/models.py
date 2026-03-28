from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.utils import timezone
from apps.core.models import BranchScopedModel


class Medicine(BranchScopedModel):
    inventory_item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pharmacy_medicines",
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=120)
    manufacturer = models.CharField(max_length=120)
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField()
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    stock_quantity = models.IntegerField(default=0)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "inventory_item"]),
            models.Index(fields=["branch", "name"]),
            models.Index(fields=["expiry_date"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.batch_number})"

    @property
    def available_quantity(self):
        return self.stock_quantity

    @property
    def has_sellable_stock(self):
        return self.available_quantity > 0

    @property
    def current_selling_price(self):
        return self.selling_price

    @property
    def current_purchase_price(self):
        return self.purchase_price


class DispenseRecord(BranchScopedModel):
    SALE_TYPE_PRESCRIPTION = "prescription"
    SALE_TYPE_WALK_IN = "walk_in"
    SALE_TYPE_CHOICES = [
        (SALE_TYPE_PRESCRIPTION, "Doctor Prescription"),
        (SALE_TYPE_WALK_IN, "Walk-In Sale"),
    ]

    sale_type = models.CharField(
        max_length=20,
        choices=SALE_TYPE_CHOICES,
        default=SALE_TYPE_PRESCRIPTION,
    )
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, null=True, blank=True
    )
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dispense_records",
    )
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT)
    dispensed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="dispensed_records",
    )
    prescribed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prescribed_dispenses",
    )
    prescription_notes = models.TextField(blank=True)
    walk_in_name = models.CharField(max_length=255, blank=True)
    walk_in_phone = models.CharField(max_length=50, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    unit_cost_snapshot = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost_snapshot = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    profit_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "dispensed_at"]),
            models.Index(fields=["branch", "patient", "dispensed_at"]),
        ]

    def __str__(self):
        client = self.patient or self.walk_in_name or "Walk-in"
        return f"{client} - {self.medicine.name} x{self.quantity}"

    @property
    def total_amount(self):
        return (self.unit_price * Decimal(self.quantity)).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

        if self.sale_type == self.SALE_TYPE_WALK_IN:
            if not (self.walk_in_name or "").strip():
                raise ValidationError(
                    {"walk_in_name": "Walk-in customer name is required."}
                )
            if not (self.walk_in_phone or "").strip():
                raise ValidationError(
                    {"walk_in_phone": "Walk-in customer phone is required."}
                )
        else:
            self.walk_in_name = ""
            self.walk_in_phone = ""
            if not self.patient_id and not self.visit_id:
                raise ValidationError(
                    {
                        "patient": "Select a patient or visit for doctor-prescribed dispensing."
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()

        # Deduct stock only on initial dispensing to keep updates idempotent.
        if not self.pk:
            with transaction.atomic():
                allocations = []
                medicine = (
                    Medicine.objects.select_for_update()
                    .filter(pk=self.medicine_id)
                    .first()
                )
                if not medicine:
                    raise ValidationError("Selected medicine does not exist.")

                if medicine.inventory_item_id:
                    from apps.pharmacy.services import (
                        allocate_inventory_stock_for_medicine,
                        sync_medicine_catalog_for_item,
                    )

                    sync_medicine_catalog_for_item(medicine.inventory_item)
                    medicine.refresh_from_db()
                    if medicine.available_quantity < self.quantity:
                        raise ValidationError(
                            {
                                "quantity": f"Only {medicine.available_quantity} units available in stock."
                            }
                        )

                    if not self.unit_price:
                        self.unit_price = medicine.current_selling_price

                    allocations = allocate_inventory_stock_for_medicine(
                        medicine=medicine,
                        quantity=self.quantity,
                        dispensed_by=self.dispensed_by,
                        reference=(
                            f"Pharmacy dispense for visit {self.visit_id}"
                            if self.visit_id
                            else f"Walk-in pharmacy dispense {timezone.now():%Y%m%d%H%M%S}"
                        ),
                        unit_price=self.unit_price,
                    )
                    total_cost = sum(
                        (allocation["total_cost"] for allocation in allocations),
                        Decimal("0.00"),
                    ).quantize(Decimal("0.01"))
                    self.total_cost_snapshot = total_cost
                    self.unit_cost_snapshot = (
                        (total_cost / Decimal(self.quantity)).quantize(
                            Decimal("0.0001")
                        )
                        if self.quantity
                        else Decimal("0.0000")
                    )
                    self.profit_amount = self.total_amount - total_cost
                    medicine.refresh_from_db()
                else:
                    if medicine.stock_quantity < self.quantity:
                        raise ValidationError(
                            {
                                "quantity": f"Only {medicine.stock_quantity} units available in stock."
                            }
                        )

                    if not self.unit_price:
                        self.unit_price = medicine.selling_price

                    medicine.stock_quantity -= self.quantity
                    medicine.save(update_fields=["stock_quantity", "updated_at"])
                    total_cost = (
                        medicine.purchase_price * Decimal(self.quantity)
                    ).quantize(Decimal("0.01"))
                    self.total_cost_snapshot = total_cost
                    self.unit_cost_snapshot = medicine.purchase_price.quantize(
                        Decimal("0.0001")
                    )
                    self.profit_amount = self.total_amount - total_cost
                super().save(*args, **kwargs)
                if allocations:
                    DispenseBatchAllocation.objects.bulk_create(
                        [
                            DispenseBatchAllocation(
                                branch=self.branch,
                                dispense_record=self,
                                item=allocation["item"],
                                batch=allocation["batch"],
                                quantity=allocation["quantity"],
                                unit_cost_snapshot=allocation["unit_cost"],
                                unit_price_snapshot=allocation["unit_price"],
                                total_cost=allocation["total_cost"],
                                total_amount=allocation["total_amount"],
                            )
                            for allocation in allocations
                        ]
                    )
            return

        super().save(*args, **kwargs)


class DispenseBatchAllocation(BranchScopedModel):
    dispense_record = models.ForeignKey(
        DispenseRecord,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.PROTECT,
        related_name="pharmacy_dispense_allocations",
    )
    batch = models.ForeignKey(
        "inventory.Batch",
        on_delete=models.PROTECT,
        related_name="pharmacy_dispense_allocations",
    )
    quantity = models.PositiveIntegerField()
    unit_cost_snapshot = models.DecimalField(max_digits=14, decimal_places=4)
    unit_price_snapshot = models.DecimalField(max_digits=14, decimal_places=2)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "dispense_record"]),
            models.Index(fields=["branch", "item", "created_at"]),
            models.Index(fields=["branch", "batch", "created_at"]),
        ]

    def __str__(self):
        return f"Dispense #{self.dispense_record_id} - {self.batch.batch_number} x{self.quantity}"


class PharmacyRequest(BranchScopedModel):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("dispensed", "Dispensed"),
        ("cancelled", "Cancelled"),
    ]

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pharmacy_requests",
    )
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="pharmacy_requests_made",
    )
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="requested"
    )
    date_requested = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "status", "date_requested"]),
            models.Index(fields=["branch", "patient", "date_requested"]),
        ]

    def save(self, *args, **kwargs):
        if not self.unit_price_snapshot and self.medicine_id:
            if self.medicine.inventory_item_id:
                from apps.pharmacy.services import sync_medicine_catalog_for_item

                sync_medicine_catalog_for_item(self.medicine.inventory_item)
                self.medicine.refresh_from_db()
            self.unit_price_snapshot = self.medicine.current_selling_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient} - {self.medicine.name} x{self.quantity} ({self.get_status_display()})"


class MedicalStoreRequest(BranchScopedModel):
    REQUESTED_FOR_CHOICES = [
        ("pharmacy", "Pharmacy Store"),
        ("laboratory", "Laboratory Store"),
        ("radiology", "Radiology Store"),
    ]

    REQUESTED_UNIT_CHOICES = [
        ("", "General"),
        ("xray", "X-Ray Unit"),
        ("ultrasound", "Ultrasound Unit"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("fulfilled", "Fulfilled"),
        ("rejected", "Rejected"),
    ]

    item = models.ForeignKey(
        "inventory.Item",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="medical_store_requests",
    )
    stock_item = models.ForeignKey(
        "inventory.StockItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pharmacy_requests",
    )
    medicine_name = models.CharField(max_length=255)
    category = models.CharField(max_length=120, blank=True)
    requested_for = models.CharField(
        max_length=20,
        choices=REQUESTED_FOR_CHOICES,
        default="pharmacy",
    )
    requested_unit = models.CharField(
        max_length=20,
        choices=REQUESTED_UNIT_CHOICES,
        blank=True,
        default="",
    )
    quantity_requested = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    decision_remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="medical_store_requests",
    )
    handled_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_store_requests_handled",
    )
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "status", "created_at"]),
            models.Index(fields=["branch", "requested_for", "status"]),
            models.Index(
                fields=["branch", "requested_for", "requested_unit", "status"]
            ),
            models.Index(fields=["branch", "medicine_name"]),
        ]

    @property
    def requested_item(self):
        return self.item or self.stock_item

    @property
    def available_quantity(self):
        if self.item_id:
            from apps.pharmacy.services import sellable_quantity_for_item

            return sellable_quantity_for_item(self.item)
        if self.stock_item_id:
            return self.stock_item.quantity
        return 0

    @property
    def request_scope_label(self):
        if self.requested_for == "radiology" and self.requested_unit:
            return self.get_requested_unit_display()
        return self.get_requested_for_display()

    def __str__(self):
        return f"{self.medicine_name} x{self.quantity_requested} ({self.request_scope_label})"
