from django import forms
from django.contrib.auth import get_user_model

from apps.consultation.models import Consultation
from apps.laboratory.forms import LAB_TEST_CHOICES
from apps.pharmacy.models import Medicine
from apps.pharmacy.services import (
    available_medicines_queryset,
    sync_branch_medicine_catalog,
)
from apps.radiology.models import ImagingRequest


CONSULTATION_ROOM_CHOICES = [
    ("Consultation Room 1", "Consultation Room 1"),
    ("Consultation Room 2", "Consultation Room 2"),
    ("Consultation Room 3", "Consultation Room 3"),
    ("Consultation Room 4", "Consultation Room 4"),
    ("Consultation Room 5", "Consultation Room 5"),
]


class ConsultationForm(forms.ModelForm):
    consultation_room = forms.ChoiceField(choices=CONSULTATION_ROOM_CHOICES)

    class Meta:
        model = Consultation
        fields = [
            "consultation_room",
            "symptoms",
            "diagnosis",
            "treatment_plan",
            "prescription",
            "lab_tests_requested",
            "follow_up_date",
        ]
        widgets = {
            "symptoms": forms.Textarea(attrs={"rows": 2}),
            "diagnosis": forms.Textarea(attrs={"rows": 2}),
            "treatment_plan": forms.Textarea(attrs={"rows": 2}),
            "prescription": forms.Textarea(attrs={"rows": 2}),
            "lab_tests_requested": forms.Textarea(attrs={"rows": 1}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class ConsultationLabTestRequestForm(forms.Form):
    test_type = forms.ChoiceField(choices=LAB_TEST_CHOICES, required=False)
    external_test_name = forms.CharField(max_length=120, required=False)
    comments = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

    def clean(self):
        cleaned = super().clean()
        test_type = (cleaned.get("test_type") or "").strip()
        external_test_name = (cleaned.get("external_test_name") or "").strip()

        if not test_type and not external_test_name:
            raise forms.ValidationError(
                "Choose an available test or enter an external test name."
            )
        if test_type and external_test_name:
            raise forms.ValidationError(
                "Use either available test selection or external test name, not both."
            )
        return cleaned


class ConsultationRadiologyRequestForm(forms.Form):
    imaging_type = forms.ChoiceField(choices=ImagingRequest.IMAGING_TYPE_CHOICES)
    priority = forms.ChoiceField(choices=ImagingRequest.PRIORITY_CHOICES)
    clinical_notes = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class ConsultationReferralRequestForm(forms.Form):
    facility_name = forms.CharField(max_length=255)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class ConsultationPharmacyLineForm(forms.Form):
    """Single medicine line – used inside a formset."""

    medicine = forms.ModelChoiceField(queryset=Medicine.objects.none())
    quantity = forms.IntegerField(min_value=1, initial=1)

    def __init__(self, *args, **kwargs):
        medicines_qs = kwargs.pop("medicines_qs", Medicine.objects.none())
        super().__init__(*args, **kwargs)
        self.fields["medicine"].queryset = medicines_qs
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css
        self.fields["medicine"].widget.attrs.update(
            {
                "class": f"{self.fields['medicine'].widget.attrs.get('class', '')} consult-medicine-select".strip(),
                "data-role": "medicine-select",
            }
        )
        self.fields["quantity"].widget.attrs.update(
            {
                "class": f"{self.fields['quantity'].widget.attrs.get('class', '')} consult-quantity-input".strip(),
                "placeholder": "Qty",
            }
        )


class BasePharmacyLineFormSet(forms.BaseFormSet):
    """Pass medicines_qs into every child form."""

    def __init__(self, *args, **kwargs):
        self.medicines_qs = kwargs.pop("medicines_qs", Medicine.objects.none())
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["medicines_qs"] = self.medicines_qs
        return kwargs


PharmacyLineFormSet = forms.formset_factory(
    ConsultationPharmacyLineForm,
    formset=BasePharmacyLineFormSet,
    extra=1,
    max_num=20,
    validate_max=True,
)


def build_pharmacy_formset(user, data=None):
    """Build the multi-line pharmacy formset, syncing catalogue first."""
    if user is not None and getattr(user, "branch", None):
        sync_branch_medicine_catalog(user.branch)
    medicines = available_medicines_queryset().order_by("name")
    if user is not None and not user.can_view_all_branches:
        medicines = medicines.filter(branch_id=user.branch_id)
    return PharmacyLineFormSet(
        data,
        prefix="pharm",
        medicines_qs=medicines,
    )


class ConsultationPharmacyRequestForm(forms.Form):
    medicine = forms.ModelChoiceField(queryset=Medicine.objects.none())
    quantity = forms.IntegerField(min_value=1, initial=1)
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user is not None and getattr(user, "branch", None):
            sync_branch_medicine_catalog(user.branch)

        medicines = available_medicines_queryset().order_by("name")
        if user is not None and not user.can_view_all_branches:
            medicines = medicines.filter(branch_id=user.branch_id)
        self.fields["medicine"].queryset = medicines

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class ConsultationTransferForm(forms.Form):
    clinician = forms.ModelChoiceField(queryset=get_user_model().objects.none())
    consultation_room = forms.ChoiceField(choices=CONSULTATION_ROOM_CHOICES)
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        clinicians = get_user_model().objects.filter(role="doctor")
        if user is not None and not user.can_view_all_branches:
            clinicians = clinicians.filter(branch_id=user.branch_id)

        self.fields["clinician"].queryset = clinicians.order_by("username")

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css
