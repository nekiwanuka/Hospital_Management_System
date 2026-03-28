from django import forms

from apps.core.permissions import branch_queryset_for_user
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.visits.models import Visit


LAB_TEST_CHOICES = [
    ("", "Select test"),
    ("CBC", "CBC"),
    ("Blood glucose", "Blood glucose"),
    ("Urinalysis", "Urinalysis"),
    ("Malaria test", "Malaria test"),
    ("HIV test", "HIV test"),
    ("Liver function tests", "Liver function tests"),
    ("Kidney function tests", "Kidney function tests"),
    ("Stool examination", "Stool examination"),
    ("Lipid profile", "Lipid profile"),
    ("Pregnancy test", "Pregnancy test"),
]


class LabRequestForm(forms.ModelForm):
    test_type = forms.ChoiceField(choices=LAB_TEST_CHOICES)

    class Meta:
        model = LabRequest
        fields = ["visit", "patient", "test_type", "comments"]
        widgets = {
            "comments": forms.Textarea(attrs={"rows": 3}),
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
                .filter(status="waiting_doctor")
                .filter(check_out_time__isnull=True)
                .order_by("-check_in_time"),
            )

    def clean(self):
        cleaned_data = super().clean()
        visit = cleaned_data.get("visit")
        patient = cleaned_data.get("patient")

        if not visit:
            self.add_error("visit", "A visit is required for laboratory request flow.")
            return cleaned_data

        if visit and patient and visit.patient_id != patient.id:
            self.add_error(
                "visit", "Selected visit does not belong to selected patient."
            )
        if visit and not patient:
            cleaned_data["patient"] = visit.patient
        return cleaned_data


class LabResultForm(forms.ModelForm):
    class Meta:
        model = LabRequest
        fields = ["status", "sample_collected", "results", "comments"]
        widgets = {
            "results": forms.Textarea(attrs={"rows": 4}),
            "comments": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            field.widget.attrs["class"] = css

        self.fields["status"].choices = [
            ("processing", "Processing"),
            ("completed", "Completed"),
        ]
