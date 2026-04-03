from django import forms

from apps.admission.models import Admission, Bed, NursingNote, VitalSign
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
