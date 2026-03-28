from decimal import Decimal

from django import forms
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    Item,
    StockIssue,
    StockItem,
    Supplier,
)
from apps.inventory.services import store_department_for_service
from apps.patients.models import Patient


class StockItemForm(forms.ModelForm):
    class Meta:
        model = StockItem
        fields = [
            "item_name",
            "category",
            "department",
            "service_type",
            "service_code",
            "quantity",
            "reorder_level",
            "stock_rate",
            "charge_rate",
            "expiry_date",
            "is_active",
        ]
        widgets = {
            "expiry_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            field.widget.attrs["class"] = css

    def clean_service_code(self):
        value = (self.cleaned_data.get("service_code") or "").strip().lower()
        return value.replace(" ", "_")


class StockIssueForm(forms.ModelForm):
    class Meta:
        model = StockIssue
        fields = ["stock_item", "issued_to", "quantity", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user and getattr(user, "branch_id", None):
            self.fields["stock_item"].queryset = StockItem.objects.filter(
                branch_id=user.branch_id,
                is_active=True,
            ).order_by("item_name")

    def clean(self):
        cleaned = super().clean()
        stock_item = cleaned.get("stock_item")
        qty = cleaned.get("quantity") or 0

        if stock_item and qty > stock_item.quantity:
            self.add_error("quantity", f"Only {stock_item.quantity} in stock.")
        return cleaned


class MedicalStoreEntryForm(forms.Form):
    DOSAGE_FORM_CHOICES = Item.DOSAGE_FORM_CHOICES
    STORE_DEPARTMENT_CHOICES = Item.STORE_DEPARTMENT_CHOICES
    SERVICE_TYPE_CHOICES = Item.SERVICE_TYPE_CHOICES

    item_name = forms.CharField(max_length=255)
    generic_name = forms.CharField(max_length=255, required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.none(), required=False)
    new_category_name = forms.CharField(max_length=120, required=False)
    brand = forms.ModelChoiceField(queryset=Brand.objects.none(), required=False)
    new_brand_name = forms.CharField(max_length=120, required=False)
    dosage_form = forms.ChoiceField(choices=DOSAGE_FORM_CHOICES)
    strength = forms.CharField(max_length=120, required=False)
    unit_of_measure = forms.CharField(max_length=60)
    pack_size = forms.CharField(max_length=60, required=False)
    barcode = forms.CharField(max_length=120, required=False)
    store_department = forms.ChoiceField(
        choices=STORE_DEPARTMENT_CHOICES,
        required=False,
        initial="pharmacy",
    )
    service_type = forms.ChoiceField(choices=SERVICE_TYPE_CHOICES, required=False)
    service_code = forms.CharField(max_length=120, required=False)
    reorder_level = forms.IntegerField(min_value=0, initial=10)
    description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False
    )

    batch_number = forms.CharField(max_length=120)
    mfg_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    exp_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    batch_barcode = forms.CharField(max_length=120, required=False)
    weight = forms.CharField(max_length=60, required=False)
    volume = forms.CharField(max_length=60, required=False)

    pack_size_units = forms.IntegerField(min_value=1, initial=100)
    packs_received = forms.IntegerField(min_value=1, initial=1)
    purchase_price_per_pack = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=0.01
    )
    target_profit_margin = forms.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=0,
        max_value=Decimal("99.99"),
        initial=25,
    )
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.none(), required=False)
    new_supplier_name = forms.CharField(max_length=180, required=False)
    supplier_contact = forms.CharField(max_length=120, required=False)
    supplier_address = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        store_department = kwargs.pop("store_department", "")
        super().__init__(*args, **kwargs)
        self.user = user
        self.store_department = (
            store_department
            if store_department in dict(self.STORE_DEPARTMENT_CHOICES)
            else ""
        )

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if self.store_department:
            self.fields["store_department"].initial = self.store_department
            self.fields["store_department"].widget = forms.HiddenInput()
            self.fields["service_type"].widget = forms.HiddenInput()
            self.fields["service_code"].widget = forms.HiddenInput()

        if user is not None and getattr(user, "branch_id", None):
            self.fields["category"].queryset = Category.objects.filter(
                branch_id=user.branch_id
            ).order_by("name")
            self.fields["brand"].queryset = Brand.objects.filter(
                branch_id=user.branch_id
            ).order_by("name")
            self.fields["supplier"].queryset = Supplier.objects.filter(
                branch_id=user.branch_id
            ).order_by("name")

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get("category")
        brand = cleaned.get("brand")
        supplier = cleaned.get("supplier")

        new_category_name = (cleaned.get("new_category_name") or "").strip()
        new_brand_name = (cleaned.get("new_brand_name") or "").strip()
        new_supplier_name = (cleaned.get("new_supplier_name") or "").strip()

        if not category and not new_category_name:
            self.add_error("category", "Select a category or add a new one.")
        if not brand and not new_brand_name:
            self.add_error("brand", "Select a brand or add a new one.")

        store_department = (
            self.store_department or cleaned.get("store_department") or "pharmacy"
        )
        cleaned["store_department"] = store_department

        # Auto-derive service_type from store_department
        store_to_service = {
            "laboratory": "lab",
            "xray": "radiology",
            "ultrasound": "radiology",
            "radiology": "radiology",
        }
        cleaned["service_type"] = store_to_service.get(store_department, "")
        cleaned["service_code"] = (
            (cleaned.get("service_code") or "").strip().lower().replace(" ", "_")
        )

        exp_date = cleaned.get("exp_date")
        if exp_date and exp_date <= timezone.localdate():
            self.add_error("exp_date", "No expired stock entry is allowed.")

        pack_size_units = cleaned.get("pack_size_units")
        packs_received = cleaned.get("packs_received")
        purchase_price_per_pack = cleaned.get("purchase_price_per_pack")
        wholesale_price_per_pack = cleaned.get("wholesale_price_per_pack")
        retail_price_per_unit = cleaned.get("retail_price_per_unit")

        if pack_size_units and pack_size_units <= 0:
            self.add_error("pack_size_units", "Pack size must be greater than zero.")
        if packs_received and packs_received <= 0:
            self.add_error("packs_received", "Packs received must be positive.")

        if purchase_price_per_pack and purchase_price_per_pack <= 0:
            self.add_error(
                "purchase_price_per_pack",
                "Purchase price per pack must be positive.",
            )

        if (
            wholesale_price_per_pack
            and purchase_price_per_pack
            and wholesale_price_per_pack < purchase_price_per_pack
        ):
            self.add_error(
                "wholesale_price_per_pack",
                "Wholesale price per pack cannot be below purchase price per pack.",
            )

        if pack_size_units and purchase_price_per_pack and retail_price_per_unit:
            unit_cost = purchase_price_per_pack / Decimal(pack_size_units)
            if retail_price_per_unit < unit_cost:
                self.add_error(
                    "retail_price_per_unit",
                    "Retail price per unit cannot be below unit cost.",
                )

        if pack_size_units and packs_received and purchase_price_per_pack:
            cleaned["quantity_received"] = pack_size_units * packs_received
            cleaned["purchase_price_total"] = (
                Decimal(packs_received) * purchase_price_per_pack
            )

        if not supplier and new_supplier_name:
            cleaned["_new_supplier_name"] = new_supplier_name

        cleaned["_new_category_name"] = new_category_name
        cleaned["_new_brand_name"] = new_brand_name
        return cleaned

    @property
    def preview_unit_cost(self):
        if not self.is_bound:
            return None
        try:
            pack_size = int(self.data.get("pack_size_units", "0") or "0")
            purchase_per_pack = float(
                self.data.get("purchase_price_per_pack", "0") or "0"
            )
            if pack_size > 0 and purchase_per_pack > 0:
                return round(purchase_per_pack / pack_size, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        return None

    @property
    def preview_selling_price(self):
        if not self.is_bound:
            return None
        try:
            pack_size = int(self.data.get("pack_size_units", "0") or "0")
            purchase_per_pack = float(
                self.data.get("purchase_price_per_pack", "0") or "0"
            )
            margin = float(self.data.get("target_profit_margin", "0") or "0")
            if pack_size > 0 and purchase_per_pack > 0:
                unit_cost = purchase_per_pack / pack_size
                if 0 < margin < 100:
                    return round(unit_cost / (1 - margin / 100), 2)
                return round(unit_cost, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        return None

    @property
    def preview_profit_margin_unit(self):
        if not self.is_bound:
            return None
        try:
            pack_size = int(self.data.get("pack_size_units", "0") or "0")
            purchase_per_pack = float(
                self.data.get("purchase_price_per_pack", "0") or "0"
            )
            margin = float(self.data.get("target_profit_margin", "0") or "0")
            if pack_size > 0 and purchase_per_pack > 0 and 0 < margin < 100:
                unit_cost = purchase_per_pack / pack_size
                selling = unit_cost / (1 - margin / 100)
                return round(selling - unit_cost, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        return None


class MedicalStoreDispenseForm(forms.Form):
    SALE_MODE_CHOICES = [
        ("unit", "Sell By Unit"),
        ("pack", "Sell By Pack"),
    ]

    patient = forms.ModelChoiceField(queryset=Patient.objects.none())
    item = forms.ModelChoiceField(queryset=Item.objects.none())
    sale_mode = forms.ChoiceField(choices=SALE_MODE_CHOICES, initial="unit")
    quantity = forms.IntegerField(min_value=1, initial=1)
    reference = forms.CharField(max_length=180, required=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.user = user

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user is not None and getattr(user, "branch_id", None):
            self.fields["patient"].queryset = Patient.objects.filter(
                branch_id=user.branch_id
            ).order_by("last_name", "first_name")
            self.fields["item"].queryset = Item.objects.filter(
                branch_id=user.branch_id,
                is_active=True,
                store_department__in=["pharmacy", "general"],
            ).order_by("item_name")
            self.fields["item"].label_from_instance = (
                lambda obj: f"{obj.item_name} ({obj.default_pack_size_units}/pack)"
            )

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get("item")
        sale_mode = cleaned.get("sale_mode")
        quantity = cleaned.get("quantity") or 0

        if not item or quantity <= 0:
            return cleaned

        units_to_deduct = quantity
        if sale_mode == "pack":
            if item.default_pack_size_units <= 0:
                self.add_error("item", "This item has invalid pack size configuration.")
                return cleaned
            units_to_deduct = quantity * item.default_pack_size_units

        if units_to_deduct > item.quantity_on_hand:
            self.add_error(
                "quantity",
                f"Cannot sell {units_to_deduct} unit(s). Available stock is {item.quantity_on_hand} unit(s).",
            )

        cleaned["units_to_deduct"] = units_to_deduct
        return cleaned


class AvailableInventoryItemChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        available = getattr(obj, "available_quantity", obj.quantity_on_hand)
        return (
            f"{obj.item_name} [{obj.get_store_department_display()}] - "
            f"{available} {obj.unit_of_measure} available"
        )


class ServiceConsumableLineForm(forms.Form):
    item = AvailableInventoryItemChoiceField(
        queryset=Item.objects.none(),
        required=False,
        empty_label="Select stock item",
    )
    quantity = forms.IntegerField(min_value=1, required=False)

    def __init__(self, *args, **kwargs):
        branch = kwargs.pop("branch", None)
        store_department = kwargs.pop("store_department", "")
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        queryset = Item.objects.none()
        if branch and store_department:
            queryset = (
                Item.objects.filter(
                    branch=branch,
                    store_department=store_department,
                    is_active=True,
                )
                .annotate(
                    available_quantity=Coalesce(Sum("batches__quantity_remaining"), 0)
                )
                .filter(available_quantity__gt=0)
                .order_by("item_name")
            )
        self.fields["item"].queryset = queryset

    def clean(self):
        cleaned = super().clean()
        item = cleaned.get("item")
        quantity = cleaned.get("quantity")

        if not item and not quantity:
            return {}

        if item and not quantity:
            self.add_error("quantity", "Enter quantity to use.")
            return cleaned

        if quantity and not item:
            self.add_error("item", "Select the stock item used.")
            return cleaned

        available = getattr(item, "available_quantity", item.quantity_on_hand)
        if quantity and available < quantity:
            self.add_error(
                "quantity",
                f"Only {available} {item.unit_of_measure} available for {item.item_name}.",
            )

        return cleaned


class BaseServiceConsumableFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        selected_items = []
        for form in self.forms:
            cleaned = getattr(form, "cleaned_data", None) or {}
            item = cleaned.get("item")
            if item:
                selected_items.append(item.pk)

        if not selected_items:
            raise forms.ValidationError(
                "Select at least one apparatus or reagent from stock before continuing."
            )

        if len(selected_items) != len(set(selected_items)):
            raise forms.ValidationError(
                "Each stock item can only be selected once per patient test."
            )


ServiceConsumableFormSet = formset_factory(
    ServiceConsumableLineForm,
    formset=BaseServiceConsumableFormSet,
    extra=4,
)


def build_service_consumable_formset(*args, branch=None, store_department="", **kwargs):
    return ServiceConsumableFormSet(
        *args,
        form_kwargs={
            "branch": branch,
            "store_department": store_department,
        },
        **kwargs,
    )


class ServiceConsumptionCorrectionForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=500,
        help_text="Explain why the original consumables must be reversed and re-entered.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
