from django import forms

from apps.admission.models import (
    Admission,
    Bed,
    DailyReport,
    DoctorOrder,
    IntakeOutput,
    MedicationAdministration,
    NursingNote,
    VitalSign,
    Ward,
)
from apps.core.permissions import branch_queryset_for_user
from apps.patients.models import Patient
from apps.visits.models import Visit


class AdmissionForm(forms.ModelForm):
    class Meta:
        model = Admission
        fields = ["visit", "patient", "bed_assigned", "doctor", "nurse", "diagnosis"]
        widgets = {
            "diagnosis": forms.Textarea(attrs={"rows": 3}),
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
            bed_field = self.fields.get("bed_assigned")
            if isinstance(bed_field, forms.ModelChoiceField):
                bed_field.queryset = branch_queryset_for_user(
                    user,
                    Bed.objects.filter(status="available")
                    .select_related("ward")
                    .order_by("ward__name", "bed_number"),
                )

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

            nurse_field = self.fields.get("nurse")
            if isinstance(nurse_field, forms.ModelChoiceField):
                nurses = user.__class__.objects.filter(role="nurse")
                if not user.can_view_all_branches:
                    nurses = nurses.filter(branch_id=user.branch_id)
                nurse_field.queryset = nurses.order_by("username")

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

    def save(self, commit=True):
        instance = super().save(commit=False)
        bed = instance.bed_assigned
        if bed:
            instance.ward = bed.ward.name
            instance.bed = bed.bed_number
            instance.ward_obj = bed.ward
        if commit:
            instance.save()
            if bed:
                Bed.objects.filter(pk=bed.pk).update(status="occupied")
        return instance


class DischargeForm(forms.ModelForm):
    class Meta:
        model = Admission
        fields = ["discharge_date", "discharge_summary"]
        widgets = {
            "discharge_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "discharge_summary": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            field.widget.attrs["class"] = css


class NursingNoteForm(forms.ModelForm):
    class Meta:
        model = NursingNote
        fields = ["category", "note"]
        widgets = {
            "note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Enter nursing note..."}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css


class VitalSignForm(forms.ModelForm):
    class Meta:
        model = VitalSign
        fields = [
            "temperature",
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "pulse_rate",
            "respiratory_rate",
            "oxygen_saturation",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Additional notes..."}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["temperature"].widget.attrs["placeholder"] = "e.g. 36.5"
        self.fields["blood_pressure_systolic"].widget.attrs["placeholder"] = "Systolic"
        self.fields["blood_pressure_diastolic"].widget.attrs[
            "placeholder"
        ] = "Diastolic"
        self.fields["pulse_rate"].widget.attrs["placeholder"] = "BPM"
        self.fields["respiratory_rate"].widget.attrs["placeholder"] = "Breaths/min"
        self.fields["oxygen_saturation"].widget.attrs["placeholder"] = "SpO2 %"
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class WardForm(forms.ModelForm):
    """Create / edit a ward."""

    auto_create_beds = forms.IntegerField(
        min_value=0,
        max_value=200,
        initial=0,
        required=False,
        label="Auto-create beds",
        help_text="Enter the number of beds to generate automatically (e.g. 10). "
        "Beds will be numbered 1, 2, 3 … Leave 0 to add beds manually later.",
    )
    bed_number_prefix = forms.CharField(
        max_length=20,
        initial="B",
        required=False,
        label="Bed number prefix",
        help_text="Prefix for auto-created beds, e.g. 'B' → B1, B2, B3 …",
    )

    class Meta:
        model = Ward
        fields = [
            "name",
            "ward_type",
            "ward_category",
            "floor",
            "capacity",
            "description",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        self._user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

        # Pre-fill daily_rate from settings based on chosen category
        from apps.settingsapp.services import get_all_ward_category_rates

        self._ward_rates = get_all_ward_category_rates()

    def save(self, commit=True):
        instance = super().save(commit=False)
        # Assign rate from settings
        instance.daily_rate = self._ward_rates.get(instance.ward_category, 0)
        if self._user and not instance.pk:
            instance.branch = self._user.branch
        if commit:
            instance.save()
            # Auto-create beds
            count = self.cleaned_data.get("auto_create_beds") or 0
            prefix = (self.cleaned_data.get("bed_number_prefix") or "B").strip()
            existing_count = instance.beds.count()
            for i in range(1, count + 1):
                bed_number = f"{prefix}{existing_count + i}"
                Bed.objects.get_or_create(
                    ward=instance,
                    bed_number=bed_number,
                    defaults={
                        "branch": instance.branch,
                        "status": "available",
                    },
                )
        return instance


class BedForm(forms.ModelForm):
    """Add / edit a single bed."""

    class Meta:
        model = Bed
        fields = ["ward", "bed_number", "status"]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["ward"].queryset = branch_queryset_for_user(
                user, Ward.objects.filter(is_active=True).order_by("name")
            )
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class MedicationAdministrationForm(forms.ModelForm):
    class Meta:
        model = MedicationAdministration
        fields = [
            "medicine_name",
            "dosage",
            "route",
            "scheduled_time",
            "administered_at",
            "status",
            "notes",
        ]
        widgets = {
            "scheduled_time": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "administered_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class WardRoundForm(forms.Form):
    findings = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Clinical findings...",
            }
        )
    )
    plan = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "class": "form-control",
                "placeholder": "Management plan...",
            }
        ),
    )


class DoctorOrderForm(forms.ModelForm):
    class Meta:
        model = DoctorOrder
        fields = ["order_type", "priority", "instruction"]
        widgets = {
            "instruction": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Enter instruction for nursing team...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class CarryOutOrderForm(forms.Form):
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Notes on how order was carried out...",
            }
        ),
        label="Carry-out Notes",
    )


class DailyReportForm(forms.ModelForm):
    class Meta:
        model = DailyReport
        fields = [
            "report_date",
            "shift",
            "general_condition",
            "diet_intake",
            "fluid_intake",
            "fluid_output",
            "mobility",
            "pain_level",
            "wound_status",
            "concerns",
            "handover_notes",
        ]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date"}),
            "general_condition": forms.Textarea(attrs={"rows": 3}),
            "wound_status": forms.Textarea(attrs={"rows": 2}),
            "concerns": forms.Textarea(attrs={"rows": 2}),
            "handover_notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class IntakeOutputForm(forms.ModelForm):
    class Meta:
        model = IntakeOutput
        fields = ["entry_type", "amount_ml", "recorded_at", "notes"]
        widgets = {
            "recorded_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.TextInput(attrs={"placeholder": "Optional notes"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"
