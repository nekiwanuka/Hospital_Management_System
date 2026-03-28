from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.permissions import branch_queryset_for_user
from apps.patients.models import Patient
from apps.radiology.models import (
    ImagingRequest,
    ImagingResult,
    RadiologyImage,
    RadiologyType,
    X_RAY_EXAMINATIONS,
    ULTRASOUND_EXAMINATIONS,
)
from apps.visits.models import Visit


class PatientChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.patient_id} - {obj.first_name} {obj.last_name}"


class ImagingRequestForm(forms.ModelForm):
    specific_examination = forms.ChoiceField(choices=[], required=False)

    class Meta:
        model = ImagingRequest
        fields = [
            "visit",
            "patient",
            "imaging_type",
            "requested_department",
            "priority",
            "specific_examination",
            "symptoms",
            "suspected_condition",
            "additional_notes",
            "last_menstrual_period",
            "pregnancy_weeks",
        ]
        widgets = {
            "symptoms": forms.Textarea(attrs={"rows": 2}),
            "suspected_condition": forms.Textarea(attrs={"rows": 2}),
            "additional_notes": forms.Textarea(attrs={"rows": 2}),
            "last_menstrual_period": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        fixed_imaging_type = kwargs.pop("fixed_imaging_type", "")
        super().__init__(*args, **kwargs)
        self.fixed_imaging_type = fixed_imaging_type

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        self.fields["patient"] = PatientChoiceField(
            queryset=self.fields["patient"].queryset,
            widget=self.fields["patient"].widget,
            required=self.fields["patient"].required,
            empty_label=self.fields["patient"].empty_label,
        )

        if user is not None:
            patient_field = self.fields["patient"]
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

        if fixed_imaging_type:
            self.fields["imaging_type"].initial = fixed_imaging_type
            self.fields["imaging_type"].widget = forms.HiddenInput()
            self.fields["imaging_type"].required = False

        imaging_type = (
            fixed_imaging_type
            or self.data.get("imaging_type")
            or self.initial.get("imaging_type")
            or getattr(self.instance, "imaging_type", "")
        )
        self.fields["specific_examination"].choices = self._get_examination_choices(
            user, imaging_type
        )

    def _get_examination_choices(self, user, imaging_type):
        if imaging_type == "xray":
            fallback_choices = X_RAY_EXAMINATIONS
        elif imaging_type == "ultrasound":
            fallback_choices = ULTRASOUND_EXAMINATIONS
        else:
            fallback_choices = []

        if not user or not imaging_type:
            return [("", "Select examination")] + fallback_choices

        queryset = branch_queryset_for_user(
            user,
            RadiologyType.objects.filter(imaging_type=imaging_type, is_active=True),
        ).order_by("examination_name")
        database_choices = [
            (item.examination_code, item.examination_name) for item in queryset
        ]
        return [("", "Select examination")] + (database_choices or fallback_choices)

    def clean(self):
        cleaned_data = super().clean()
        visit = cleaned_data.get("visit")
        patient = cleaned_data.get("patient")
        imaging_type = (
            cleaned_data.get("imaging_type")
            or self.fixed_imaging_type
            or getattr(self.instance, "imaging_type", "")
        )
        specific_examination = (cleaned_data.get("specific_examination") or "").strip()
        lmp = cleaned_data.get("last_menstrual_period")
        pregnancy_weeks = cleaned_data.get("pregnancy_weeks")

        cleaned_data["imaging_type"] = imaging_type

        if visit and patient and visit.patient_id != patient.id:
            self.add_error(
                "visit", "Selected visit does not belong to selected patient."
            )
        if visit and not patient:
            cleaned_data["patient"] = visit.patient

        if imaging_type not in {"xray", "ultrasound"}:
            self.add_error("imaging_type", "Choose X-ray or Ultrasound.")

        if not specific_examination:
            self.add_error("specific_examination", "Choose a specific examination.")

        if imaging_type != "ultrasound":
            cleaned_data["last_menstrual_period"] = None
            cleaned_data["pregnancy_weeks"] = None
        else:
            if pregnancy_weeks is not None and not lmp:
                self.add_error(
                    "last_menstrual_period",
                    "Provide last menstrual period when pregnancy weeks are entered.",
                )
            if lmp and lmp > timezone.localdate():
                self.add_error(
                    "last_menstrual_period",
                    "Last menstrual period cannot be in the future.",
                )

        symptoms = (cleaned_data.get("symptoms") or "").strip()
        suspected_condition = (cleaned_data.get("suspected_condition") or "").strip()
        additional_notes = (cleaned_data.get("additional_notes") or "").strip()
        cleaned_data["clinical_notes"] = "\n".join(
            item
            for item in [
                f"Symptoms: {symptoms}" if symptoms else "",
                (
                    f"Suspected condition: {suspected_condition}"
                    if suspected_condition
                    else ""
                ),
                f"Additional notes: {additional_notes}" if additional_notes else "",
            ]
            if item
        )
        return cleaned_data


class XRayRequestForm(ImagingRequestForm):
    def __init__(self, *args, **kwargs):
        kwargs["fixed_imaging_type"] = "xray"
        super().__init__(*args, **kwargs)


class UltrasoundRequestForm(ImagingRequestForm):
    def __init__(self, *args, **kwargs):
        kwargs["fixed_imaging_type"] = "ultrasound"
        super().__init__(*args, **kwargs)


class ImagingResultForm(forms.ModelForm):
    class Meta:
        model = ImagingResult
        fields = [
            "technician",
            "radiologist",
            "machine_used",
            "examination",
            "clinical_information",
            "image_file",
            "report_file",
            "report",
            "findings",
            "impression",
            "recommendation",
            "date_performed",
            "date_reported",
        ]
        widgets = {
            "machine_used": forms.TextInput(),
            "examination": forms.Textarea(attrs={"rows": 2}),
            "clinical_information": forms.Textarea(attrs={"rows": 2}),
            "report": forms.Textarea(attrs={"rows": 3}),
            "findings": forms.Textarea(attrs={"rows": 3}),
            "impression": forms.Textarea(attrs={"rows": 3}),
            "recommendation": forms.Textarea(attrs={"rows": 3}),
            "date_performed": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "date_reported": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            if isinstance(field.widget, forms.ClearableFileInput):
                css = "form-control"
            field.widget.attrs["class"] = css

        User = get_user_model()
        technicians = User.objects.filter(
            role__in=["radiology_technician", "lab_technician"]
        )
        radiologists = User.objects.filter(role="radiologist")

        if user is not None and not user.can_view_all_branches:
            technicians = technicians.filter(branch_id=user.branch_id)
            radiologists = radiologists.filter(branch_id=user.branch_id)

        technician_field = self.fields["technician"]
        if isinstance(technician_field, forms.ModelChoiceField):
            technician_field.queryset = technicians.order_by("username")

        radiologist_field = self.fields["radiologist"]
        if isinstance(radiologist_field, forms.ModelChoiceField):
            radiologist_field.queryset = radiologists.order_by("username")


class RadiologyImageForm(forms.ModelForm):
    class Meta:
        model = RadiologyImage
        fields = ["file_kind", "image_file", "report_file", "caption", "machine_used"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css
