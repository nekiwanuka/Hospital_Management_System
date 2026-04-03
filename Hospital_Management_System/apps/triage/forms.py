from django import forms

from apps.core.permissions import branch_queryset_for_user
from apps.triage.models import TriageRecord
from apps.triage.services import get_triage_eligible_visits, visit_has_triage_clearance
from apps.visits.models import Visit


class TriageVisitChoiceField(forms.ModelChoiceField):
    def __init__(self, *args, **kwargs):
        self.clearance_map = kwargs.pop("clearance_map", {})
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj):
        clearance = self.clearance_map.get(obj.pk, "Eligible")
        return (
            f"{obj.visit_number} - {obj.patient.patient_id} - "
            f"{obj.patient.first_name} {obj.patient.last_name} ({clearance})"
        )


class TriageRecordForm(forms.ModelForm):
    class Meta:
        model = TriageRecord
        fields = [
            "visit",
            "temperature",
            "blood_pressure",
            "pulse_rate",
            "respiratory_rate",
            "oxygen_level",
            "weight",
            "height",
            "symptoms",
            "outcome",
        ]
        widgets = {
            "temperature": forms.NumberInput(
                attrs={"placeholder": "36.5", "step": "0.1", "min": "30", "max": "45"}
            ),
            "blood_pressure": forms.TextInput(attrs={"placeholder": "120/80"}),
            "pulse_rate": forms.NumberInput(
                attrs={"placeholder": "72", "min": "20", "max": "300"}
            ),
            "respiratory_rate": forms.NumberInput(
                attrs={"placeholder": "16", "min": "5", "max": "60"}
            ),
            "oxygen_level": forms.NumberInput(
                attrs={"placeholder": "98", "min": "0", "max": "100"}
            ),
            "weight": forms.NumberInput(
                attrs={"placeholder": "70.0", "step": "0.1", "min": "0.5", "max": "500"}
            ),
            "height": forms.NumberInput(
                attrs={"placeholder": "170.0", "step": "0.1", "min": "20", "max": "300"}
            ),
            "symptoms": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Describe presenting complaints, onset, duration\u2026",
                }
            ),
        }
        help_texts = {
            "temperature": "°C (normal 36.1–37.2)",
            "blood_pressure": "mmHg — systolic/diastolic (normal ~120/80)",
            "pulse_rate": "bpm (normal 60–100)",
            "respiratory_rate": "breaths/min (normal 12–20)",
            "oxygen_level": "SpO₂ % (normal 95–100)",
            "weight": "kg",
            "height": "cm",
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        self.user = user
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user is not None:
            eligible_visits = get_triage_eligible_visits(user)
            clearance_map = {
                visit.pk: getattr(visit, "triage_clearance_label", "Eligible")
                for visit in eligible_visits
            }
            visit_queryset = branch_queryset_for_user(
                user,
                Visit.objects.select_related("patient")
                .filter(id__in=[visit.pk for visit in eligible_visits])
                .filter(check_out_time__isnull=True)
                .order_by("-check_in_time"),
            )
            self.fields["visit"] = TriageVisitChoiceField(
                queryset=visit_queryset,
                clearance_map=clearance_map,
                empty_label="Select eligible visit",
            )
            self.fields["visit"].widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned_data = super().clean()
        visit = cleaned_data.get("visit")

        if visit and visit.status != "waiting_triage":
            self.add_error("visit", "Visit is not in triage queue.")
        if visit and not visit_has_triage_clearance(self.user, visit):
            self.add_error(
                "visit",
                "Only paid visits or cashier-approved post-payment privilege visits can enter triage.",
            )
        if visit:
            cleaned_data["patient"] = visit.patient
        return cleaned_data
