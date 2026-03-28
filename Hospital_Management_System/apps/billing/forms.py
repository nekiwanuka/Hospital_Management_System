from django import forms

from apps.billing.models import Invoice
from apps.core.permissions import branch_queryset_for_user
from apps.patients.models import Patient
from apps.visits.models import Visit


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            "visit",
            "patient",
            "payment_method",
            "payment_status",
        ]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user is not None:
            self.fields["patient"].queryset = branch_queryset_for_user(
                user, Patient.objects.order_by("last_name", "first_name")
            )
            self.fields["visit"].queryset = branch_queryset_for_user(
                user,
                Visit.objects.select_related("patient")
                .filter(check_out_time__isnull=True)
                .order_by("-check_in_time"),
            )

    def clean(self):
        cleaned_data = super().clean()
        visit = cleaned_data.get("visit")
        patient = cleaned_data.get("patient")

        if visit and patient and visit.patient_id != patient.id:
            self.add_error(
                "visit", "Selected visit does not belong to selected patient."
            )
        if visit and not patient:
            cleaned_data["patient"] = visit.patient
        return cleaned_data


class LineItemPaymentForm(forms.Form):
    amount_paid = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    payment_method = forms.ChoiceField(choices=Invoice.PAYMENT_METHODS)
    transaction_id = forms.CharField(max_length=120, required=False)

    def __init__(self, *args, **kwargs):
        kwargs.pop("user", None)
        kwargs.pop("service_type", "")
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get("payment_method")
        transaction_id = (cleaned_data.get("transaction_id") or "").strip()
        if payment_method and payment_method != "cash" and not transaction_id:
            self.add_error(
                "transaction_id",
                "Transaction ID is required for non-cash payments.",
            )
        return cleaned_data


class InvoicePaymentForm(forms.Form):
    PAYMENT_OPTIONS = [
        ("paid", "Full Payment"),
        ("partial", "Partial Payment"),
        ("post_payment", "Post Payment"),
    ]

    payment_status = forms.ChoiceField(choices=PAYMENT_OPTIONS)
    amount_paid = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        required=False,
    )
    payment_method = forms.ChoiceField(choices=Invoice.PAYMENT_METHODS)
    transaction_id = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount_paid"].widget.attrs["placeholder"] = "Amount received"
        self.fields["transaction_id"].widget.attrs[
            "placeholder"
        ] = "Reference / transaction ID"
        self.fields["notes"].widget.attrs.update(
            {"rows": 2, "placeholder": "Optional notes"}
        )

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

    def clean(self):
        cleaned_data = super().clean()
        payment_status = cleaned_data.get("payment_status")
        payment_method = cleaned_data.get("payment_method")
        transaction_id = (cleaned_data.get("transaction_id") or "").strip()
        amount_paid = cleaned_data.get("amount_paid")

        if payment_status == "partial" and amount_paid is None:
            self.add_error("amount_paid", "Enter the partial payment amount.")

        if (
            payment_status in {"paid", "partial"}
            and payment_method != "cash"
            and not transaction_id
        ):
            self.add_error(
                "transaction_id",
                "Transaction ID is required for non-cash payments.",
            )

        return cleaned_data
