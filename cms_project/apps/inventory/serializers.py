from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.core.permissions import branch_queryset_for_user
from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    Dispense,
    DispenseItem,
    Item,
    Supplier,
)
from apps.inventory.services import create_dispense_with_items, record_stock_entry
from apps.patients.models import Patient


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name"]


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ["id", "name", "manufacturer", "country"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact", "address"]


class ItemSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.none(), source="category", write_only=True
    )
    brand_id = serializers.PrimaryKeyRelatedField(
        queryset=Brand.objects.none(), source="brand", write_only=True
    )
    category_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    brand_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    category = CategorySerializer(read_only=True)
    brand = BrandSerializer(read_only=True)
    quantity_on_hand = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "item_name",
            "generic_name",
            "category",
            "brand",
            "category_id",
            "brand_id",
            "category_name",
            "brand_name",
            "dosage_form",
            "strength",
            "unit_of_measure",
            "pack_size",
            "barcode",
            "reorder_level",
            "description",
            "is_active",
            "quantity_on_hand",
            "is_low_stock",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["category_id"].queryset = branch_queryset_for_user(
                request.user,
                Category.objects.order_by("name"),
            )
            self.fields["brand_id"].queryset = branch_queryset_for_user(
                request.user,
                Brand.objects.order_by("name"),
            )

    def validate(self, attrs):
        category = attrs.get("category")
        brand = attrs.get("brand")
        category_name = (attrs.pop("category_name", "") or "").strip()
        brand_name = (attrs.pop("brand_name", "") or "").strip()

        request = self.context["request"]
        user = request.user

        if not category:
            if not category_name:
                raise serializers.ValidationError(
                    {"category_id": "Select a category or provide category_name."}
                )
            category, _ = Category.objects.get_or_create(
                branch=user.branch,
                name=category_name,
            )
            attrs["category"] = category

        if not brand:
            if not brand_name:
                raise serializers.ValidationError(
                    {"brand_id": "Select a brand or provide brand_name."}
                )
            brand, _ = Brand.objects.get_or_create(
                branch=user.branch,
                name=brand_name,
            )
            attrs["brand"] = brand

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["branch"] = request.user.branch
        return super().create(validated_data)


class BatchSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.item_name", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    retail_price_per_unit = serializers.DecimalField(
        source="selling_price_per_unit", max_digits=14, decimal_places=2, read_only=True
    )
    wholesale_unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )
    profit_per_unit = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )
    profit_per_pack = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    profit_margin_unit = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )
    profit_margin_pack = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True
    )

    class Meta:
        model = Batch
        fields = [
            "id",
            "item",
            "item_name",
            "batch_number",
            "mfg_date",
            "exp_date",
            "pack_size_units",
            "packs_received",
            "quantity_received",
            "quantity_remaining",
            "purchase_price_per_pack",
            "purchase_price_total",
            "wholesale_price_per_pack",
            "wholesale_unit_price",
            "unit_cost",
            "selling_price_per_unit",
            "retail_price_per_unit",
            "profit_per_unit",
            "profit_per_pack",
            "profit_margin_unit",
            "profit_margin_pack",
            "profit_margin",
            "supplier",
            "supplier_name",
            "barcode",
            "weight",
            "volume",
            "date_received",
        ]
        read_only_fields = ["unit_cost", "profit_margin", "quantity_remaining"]


class BatchStockEntrySerializer(serializers.ModelSerializer):
    item_id = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.none(), source="item"
    )
    supplier_id = serializers.PrimaryKeyRelatedField(
        queryset=Supplier.objects.none(),
        source="supplier",
        required=False,
        allow_null=True,
    )
    supplier_name = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    supplier_contact = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    supplier_address = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    class Meta:
        model = Batch
        fields = [
            "id",
            "item_id",
            "batch_number",
            "mfg_date",
            "exp_date",
            "pack_size_units",
            "packs_received",
            "purchase_price_per_pack",
            "wholesale_price_per_pack",
            "selling_price_per_unit",
            "quantity_received",
            "purchase_price_total",
            "supplier_id",
            "supplier_name",
            "supplier_contact",
            "supplier_address",
            "barcode",
            "weight",
            "volume",
            "date_received",
            "unit_cost",
            "profit_margin",
        ]
        read_only_fields = [
            "unit_cost",
            "profit_margin",
            "quantity_received",
            "purchase_price_total",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["item_id"].queryset = branch_queryset_for_user(
                request.user, Item.objects.order_by("item_name")
            )
            self.fields["supplier_id"].queryset = branch_queryset_for_user(
                request.user, Supplier.objects.order_by("name")
            )

    def validate(self, attrs):
        supplier = attrs.get("supplier")
        supplier_name = (attrs.pop("supplier_name", "") or "").strip()
        supplier_contact = (attrs.pop("supplier_contact", "") or "").strip()
        supplier_address = (attrs.pop("supplier_address", "") or "").strip()
        request = self.context["request"]

        if attrs["pack_size_units"] <= 0:
            raise serializers.ValidationError(
                {"pack_size_units": "Pack size must be greater than zero."}
            )

        if attrs["packs_received"] <= 0:
            raise serializers.ValidationError(
                {"packs_received": "Packs received must be positive."}
            )

        if attrs["purchase_price_per_pack"] <= 0:
            raise serializers.ValidationError(
                {"purchase_price_per_pack": "Purchase price per pack must be positive."}
            )

        if attrs["wholesale_price_per_pack"] < attrs["purchase_price_per_pack"]:
            raise serializers.ValidationError(
                {
                    "wholesale_price_per_pack": "Wholesale price per pack cannot be below purchase price per pack."
                }
            )

        if attrs["exp_date"] <= timezone.localdate():
            raise serializers.ValidationError(
                {"exp_date": "No expired stock entry is allowed."}
            )

        attrs["quantity_received"] = attrs["pack_size_units"] * attrs["packs_received"]
        attrs["purchase_price_total"] = (
            Decimal(attrs["packs_received"]) * attrs["purchase_price_per_pack"]
        )

        if attrs["quantity_received"] <= 0:
            raise serializers.ValidationError(
                {"quantity_received": "Quantity must be positive."}
            )

        unit_cost = attrs["purchase_price_per_pack"] / Decimal(attrs["pack_size_units"])
        if attrs["selling_price_per_unit"] < unit_cost:
            raise serializers.ValidationError(
                {
                    "selling_price_per_unit": "Retail price per unit cannot be below unit cost."
                }
            )

        if not supplier and supplier_name:
            supplier, _ = Supplier.objects.get_or_create(
                branch=request.user.branch,
                name=supplier_name,
                defaults={
                    "contact": supplier_contact,
                    "address": supplier_address,
                },
            )
            attrs["supplier"] = supplier

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user

        with transaction.atomic():
            try:
                batch = Batch.objects.create(
                    branch=user.branch,
                    created_by=user,
                    **validated_data,
                )
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.message_dict)
            record_stock_entry(
                batch, user, reference=f"Stock entry {batch.batch_number}"
            )
        return batch


class DispenseItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.item_name", read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)

    class Meta:
        model = DispenseItem
        fields = [
            "id",
            "item",
            "item_name",
            "batch",
            "batch_number",
            "quantity",
            "unit_price",
            "total_price",
        ]


class DispenseSerializer(serializers.ModelSerializer):
    items = DispenseItemSerializer(many=True, read_only=True)

    class Meta:
        model = Dispense
        fields = ["id", "patient", "total_amount", "date", "reference", "items"]


class DispenseLineInputSerializer(serializers.Serializer):
    SALE_MODE_CHOICES = (("unit", "Unit"), ("pack", "Pack"))

    item_id = serializers.PrimaryKeyRelatedField(
        queryset=Item.objects.none(), source="item"
    )
    quantity = serializers.IntegerField(min_value=1)
    sale_mode = serializers.ChoiceField(
        choices=SALE_MODE_CHOICES, required=False, default="unit"
    )
    unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["item_id"].queryset = branch_queryset_for_user(
                request.user,
                Item.objects.filter(is_active=True).order_by("item_name"),
            )

    def validate(self, attrs):
        item = attrs["item"]
        quantity = attrs["quantity"]
        sale_mode = attrs.get("sale_mode", "unit")

        if sale_mode == "pack":
            if item.default_pack_size_units <= 0:
                raise serializers.ValidationError(
                    {"sale_mode": "This item has invalid pack size configuration."}
                )
            attrs["quantity"] = quantity * item.default_pack_size_units

        return attrs


class DispenseCreateSerializer(serializers.Serializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        queryset=Patient.objects.none(), source="patient"
    )
    reference = serializers.CharField(required=False, allow_blank=True)
    items = DispenseLineInputSerializer(many=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            self.fields["patient_id"].queryset = branch_queryset_for_user(
                request.user,
                Patient.objects.order_by("last_name", "first_name"),
            )

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("At least one dispense line is required.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        patient = validated_data["patient"]
        item_lines = validated_data["items"]
        reference = validated_data.get("reference", "")

        dispense = create_dispense_with_items(
            branch=user.branch,
            patient=patient,
            dispensed_by=user,
            item_lines=item_lines,
            reference=reference,
        )
        return dispense


class InventoryListItemSerializer(serializers.ModelSerializer):
    category = serializers.CharField(source="category.name")
    brand = serializers.CharField(source="brand.name")
    quantity_on_hand = serializers.IntegerField(read_only=True)
    default_pack_size_units = serializers.IntegerField(read_only=True)
    equivalent_packs = serializers.SerializerMethodField()
    next_expiry = serializers.DateField(read_only=True)

    class Meta:
        model = Item
        fields = [
            "id",
            "item_name",
            "generic_name",
            "category",
            "brand",
            "barcode",
            "reorder_level",
            "quantity_on_hand",
            "default_pack_size_units",
            "equivalent_packs",
            "next_expiry",
            "is_active",
        ]

    def get_equivalent_packs(self, obj):
        if not obj.default_pack_size_units:
            return "0.00"
        return f"{Decimal(obj.quantity_on_hand) / Decimal(obj.default_pack_size_units):.2f}"


def inventory_dashboard_payload(user, queryset):
    today = timezone.localdate()
    in_30_days = today + timedelta(days=30)

    # Sum(value) without ExpressionWrapper keeps compatibility across DB backends.
    running_total = Decimal("0.00")
    for batch in Batch.objects.filter(
        branch=user.branch,
        quantity_remaining__gt=0,
        exp_date__gte=today,
    ).only("quantity_remaining", "unit_cost"):
        running_total += Decimal(batch.quantity_remaining) * batch.unit_cost

    total_units = 0
    total_equivalent_packs = Decimal("0.00")
    total_retail_value = Decimal("0.00")
    for batch in Batch.objects.filter(
        branch=user.branch, quantity_remaining__gt=0
    ).only("quantity_remaining", "pack_size_units", "selling_price_per_unit"):
        total_units += batch.quantity_remaining
        if batch.pack_size_units > 0:
            total_equivalent_packs += Decimal(batch.quantity_remaining) / Decimal(
                batch.pack_size_units
            )
        total_retail_value += (
            Decimal(batch.quantity_remaining) * batch.selling_price_per_unit
        )

    low_stock_count = sum(
        1 for item in queryset if item.quantity_on_hand <= item.reorder_level
    )
    expiring_soon_count = Batch.objects.filter(
        branch=user.branch,
        quantity_remaining__gt=0,
        exp_date__gte=today,
        exp_date__lte=in_30_days,
    ).count()
    expired_count = Batch.objects.filter(
        branch=user.branch,
        quantity_remaining__gt=0,
        exp_date__lt=today,
    ).count()

    return {
        "summary": {
            "total_units": total_units,
            "equivalent_packs": total_equivalent_packs,
            "total_stock_value": running_total,
            "total_retail_value": total_retail_value,
            "low_stock_items": low_stock_count,
            "expiring_soon_batches": expiring_soon_count,
            "expired_batches": expired_count,
        }
    }
