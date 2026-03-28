from django import forms

from apps.core.permissions import branch_queryset_for_user
from apps.emergency.models import EmergencyCase
from apps.patients.models import Patient
from apps.visits.models import Visit


class EmergencyCaseForm(forms.ModelForm):
    class Meta:
        model = EmergencyCase
        fields = ["visit", "patient", "emergency_level", "doctor", "treatment"]
        widgets = {
            "treatment": forms.Textarea(attrs={"rows": 3}),
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

            doctor_field = self.fields.get("doctor")
            if isinstance(doctor_field, forms.ModelChoiceField):
                doctors = user.__class__.objects.filter(role="doctor")
                if not user.can_view_all_branches:
                    doctors = doctors.filter(branch_id=user.branch_id)
                doctor_field.queryset = doctors.order_by("username")

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
