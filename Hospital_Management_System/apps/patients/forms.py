from django import forms

from apps.patients.models import Patient


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "first_name",
            "last_name",
            "gender",
            "date_of_birth",
            "phone",
            "email",
            "national_id",
            "marital_status",
            "occupation",
            "nationality",
            "religion",
            "address",
            "next_of_kin",
            "next_of_kin_phone",
            "next_of_kin_relationship",
            "blood_group",
            "allergies",
            "chronic_conditions",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
            "allergies": forms.Textarea(attrs={"rows": 2}),
            "chronic_conditions": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css
