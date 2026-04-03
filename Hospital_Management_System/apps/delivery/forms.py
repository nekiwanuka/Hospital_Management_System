from django import forms

from apps.delivery.models import DeliveryRecord, DeliveryNote
from apps.core.permissions import branch_queryset_for_user
from apps.patients.models import Patient
from apps.visits.models import Visit


class DeliveryRecordForm(forms.ModelForm):
    class Meta:
        model = DeliveryRecord
        fields = [
            "patient",
            "visit",
            "admission",
            "delivery_type",
            "gravida",
            "parity",
            "gestational_age_weeks",
            "delivered_by",
            "midwife",
            "notes",
        ]
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
            self.fields["visit"].required = False
            self.fields["admission"].required = False

            doctors_nurses = user.__class__.objects.filter(role__in=["doctor", "nurse"])
            if not user.can_view_all_branches:
                doctors_nurses = doctors_nurses.filter(branch_id=user.branch_id)
            self.fields["delivered_by"].queryset = doctors_nurses.order_by("username")
            self.fields["midwife"].queryset = user.__class__.objects.filter(
                role="nurse"
            ).order_by("username")
            if not user.can_view_all_branches:
                self.fields["midwife"].queryset = self.fields[
                    "midwife"
                ].queryset.filter(branch_id=user.branch_id)


class DeliveryOutcomeForm(forms.ModelForm):
    class Meta:
        model = DeliveryRecord
        fields = [
            "delivery_type",
            "delivery_datetime",
            "baby_gender",
            "baby_weight_kg",
            "apgar_score_1min",
            "apgar_score_5min",
            "outcome",
            "complications",
        ]
        widgets = {
            "delivery_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "complications": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class DeliveryDischargeForm(forms.ModelForm):
    class Meta:
        model = DeliveryRecord
        fields = ["discharge_datetime", "discharge_notes"]
        widgets = {
            "discharge_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "discharge_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class DeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = ["category", "note"]
        widgets = {
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Enter delivery note..."}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css
