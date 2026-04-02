from django import forms
from django.db.models import Q
from django.forms import formset_factory
from django.utils import timezone

from apps.core.permissions import branch_queryset_for_user
from apps.inventory.models import Item
from apps.patients.models import Patient
from apps.pharmacy.models import DispenseRecord, MedicalStoreRequest, Medicine
from apps.pharmacy.services import (
    available_medicines_queryset,
    sellable_quantity_for_item,
    sync_branch_medicine_catalog,
)
from apps.visits.models import Visit


class MedicineForm(forms.ModelForm):
    class Meta:
        model = Medicine
        fields = [
            "name",
            "category",
            "manufacturer",
            "batch_number",
            "expiry_date",
            "purchase_price",
            "selling_price",
            "stock_quantity",
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
            field.widget.attrs["class"] = css


class DispenseForm(forms.ModelForm):
    class Meta:
        model = DispenseRecord
        fields = [
            "sale_type",
            "visit",
            "patient",
            "medicine",
            "quantity",
            "prescribed_by",
            "prescription_notes",
            "walk_in_name",
            "walk_in_phone",
        ]
        widgets = {
            "prescription_notes": forms.Textarea(attrs={"rows": 3}),
            "walk_in_name": forms.TextInput(
                attrs={"placeholder": "Full name for walk-in customer"}
            ),
            "walk_in_phone": forms.TextInput(attrs={"placeholder": "Phone number"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user is not None:
            if getattr(user, "branch", None):
                sync_branch_medicine_catalog(user.branch)

            patient_field = self.fields.get("patient")
            if isinstance(patient_field, forms.ModelChoiceField):
                patient_field.queryset = branch_queryset_for_user(
                    user, Patient.objects.order_by("last_name", "first_name")
                )

            visit_field = self.fields.get("visit")
            if isinstance(visit_field, forms.ModelChoiceField):
                visit_field.queryset = branch_queryset_for_user(
                    user,
                    Visit.objects.select_related("patient")
                    .filter(check_out_time__isnull=True)
                    .order_by("-check_in_time"),
                )

            medicine_field = self.fields.get("medicine")
            if isinstance(medicine_field, forms.ModelChoiceField):
                medicine_field.queryset = branch_queryset_for_user(
                    user, available_medicines_queryset().order_by("name")
                )

            prescribed_field = self.fields.get("prescribed_by")
            if isinstance(prescribed_field, forms.ModelChoiceField):
                users = user.__class__.objects.filter(role="doctor")
                if not user.can_view_all_branches:
                    users = users.filter(branch_id=user.branch_id)
                prescribed_field.queryset = users.order_by("username")
                prescribed_field.required = False

        self.fields["walk_in_name"].required = False
        self.fields["walk_in_phone"].required = False
        self.fields["patient"].required = False
        self.fields["visit"].required = False
        self.fields["prescribed_by"].required = False

    def clean(self):
        cleaned_data = super().clean()
        sale_type = cleaned_data.get("sale_type")
        visit = cleaned_data.get("visit")
        patient = cleaned_data.get("patient")
        walk_in_name = (cleaned_data.get("walk_in_name") or "").strip()
        walk_in_phone = (cleaned_data.get("walk_in_phone") or "").strip()

        if sale_type == DispenseRecord.SALE_TYPE_WALK_IN:
            if not walk_in_name:
                self.add_error("walk_in_name", "Walk-in customer name is required.")
            if not walk_in_phone:
                self.add_error("walk_in_phone", "Walk-in customer phone is required.")
            cleaned_data["visit"] = None
            cleaned_data["patient"] = None
            cleaned_data["prescribed_by"] = None
            return cleaned_data

        cleaned_data["walk_in_name"] = ""
        cleaned_data["walk_in_phone"] = ""

        if visit and patient and visit.patient_id != patient.id:
            self.add_error(
                "visit", "Selected visit does not belong to selected patient."
            )
        if visit and not patient:
            cleaned_data["patient"] = visit.patient
        if not cleaned_data.get("patient") and not cleaned_data.get("visit"):
            self.add_error(
                "patient",
                "Select a patient or visit for doctor-prescribed dispensing.",
            )
        return cleaned_data


class MedicalStoreRequestForm(forms.ModelForm):
    item = forms.ModelChoiceField(queryset=Item.objects.none())

    class Meta:
        model = MedicalStoreRequest
        fields = ["item", "quantity_requested", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        requested_for = (
            (kwargs.pop("requested_for", "pharmacy") or "pharmacy").strip().lower()
        )
        requested_unit = (kwargs.pop("requested_unit", "") or "").strip().lower()
        super().__init__(*args, **kwargs)
        self.requested_for = requested_for
        self.requested_unit = requested_unit

        queryset = (
            Item.objects.filter(
                is_active=True,
                is_department_stock=False,
                batches__quantity_remaining__gt=0,
                batches__exp_date__gte=timezone.localdate(),
            )
            .select_related("category", "brand")
            .distinct()
            .order_by("item_name")
        )
        if user is not None and getattr(user, "branch_id", None):
            queryset = queryset.filter(branch_id=user.branch_id)

        self.fields["item"].queryset = queryset
        self.fields["item"].label = "Source Store Item (select item to request)"
        self.fields["item"].label_from_instance = (
            lambda item: f"{item.item_name} ({item.category.name}) [{item.get_store_department_display()}] - available: {sellable_quantity_for_item(item)}"
        )

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

    def clean(self):
        cleaned_data = super().clean()
        item = cleaned_data.get("item")
        qty = cleaned_data.get("quantity_requested") or 0

        if item and qty > sellable_quantity_for_item(item):
            self.add_error(
                "quantity_requested",
                f"Only {sellable_quantity_for_item(item)} units are currently available in medical stores.",
            )
        return cleaned_data


# ── Walk-in multi-item dispensing ──────────────────────────────
class WalkInCustomerForm(forms.Form):
    """Walk-in customer identification — shared across all line items."""

    walk_in_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Full name"}
        ),
    )
    walk_in_phone = forms.CharField(
        max_length=50,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Phone number"}
        ),
    )


class WalkInLineForm(forms.Form):
    """Single medicine line in a walk-in dispensing cart."""

    medicine = forms.ModelChoiceField(
        queryset=Medicine.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "1", "value": "1"}
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            if getattr(user, "branch", None):
                sync_branch_medicine_catalog(user.branch)
            self.fields["medicine"].queryset = branch_queryset_for_user(
                user, available_medicines_queryset().order_by("name")
            )


def walkin_line_formset_factory(user=None, data=None, extra=1):
    """Build a WalkInLineForm formset, injecting the user into each form."""

    class _UserBoundLineForm(WalkInLineForm):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("user", user)
            super().__init__(*args, **kwargs)

    LineFormSet = formset_factory(
        _UserBoundLineForm, extra=extra, min_num=1, validate_min=True
    )
    return LineFormSet(data=data, prefix="lines")


# ── Prescription (visit) dispense selection ────────────────────
class PrescriptionVisitSelectForm(forms.Form):
    """Let pharmacist pick a visit that has pending pharmacy requests."""

    visit = forms.ModelChoiceField(
        queryset=Visit.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Select Visit",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            from apps.pharmacy.models import PharmacyRequest

            visit_ids = PharmacyRequest.objects.filter(
                status="requested",
            ).values_list("visit_id", flat=True)
            qs = (
                Visit.objects.select_related("patient")
                .filter(pk__in=visit_ids, check_out_time__isnull=True)
                .order_by("-check_in_time")
            )
            self.fields["visit"].queryset = branch_queryset_for_user(user, qs)
            self.fields["visit"].label_from_instance = (
                lambda v: f"{v.patient.first_name} {v.patient.last_name} — Visit #{v.pk} ({v.check_in_time:%Y-%m-%d %H:%M})"
            )
