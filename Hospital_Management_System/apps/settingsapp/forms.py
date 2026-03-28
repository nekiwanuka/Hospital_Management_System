from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth import get_user_model

from apps.branches.models import Branch
from apps.laboratory.forms import LAB_TEST_CHOICES
from apps.radiology.models import ULTRASOUND_EXAMINATIONS, X_RAY_EXAMINATIONS
from apps.settingsapp.models import SystemSettings
from apps.settingsapp.services import (
    DEFAULT_CONSULTATION_FEE,
    DEFAULT_LAB_FEE,
    DEFAULT_RADIOLOGY_TYPE_RATES,
)


def _rate_field_name(prefix, code):
    safe = "".join(ch if ch.isalnum() else "_" for ch in code.lower()).strip("_")
    return f"{prefix}_{safe}"


class SystemSettingsForm(forms.ModelForm):
    """Edit form for system-wide settings (admin only)."""

    class Meta:
        model = SystemSettings
        fields = [
            "clinic_name",
            "logo",
            "primary_color",
            "secondary_color",
            "sidebar_color",
            "sidebar_text_color",
            "sidebar_text_size",
            "dashboard_color",
            "text_color",
            "system_email",
            "timezone",
            "consultation_fee",
        ]
        widgets = {
            "primary_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "secondary_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_text_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_text_size": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.70", "max": "1.20"}
            ),
            "dashboard_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "text_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
        }

    LAB_SERVICE_CHOICES = [(value, label) for value, label in LAB_TEST_CHOICES if value]
    RADIOLOGY_SERVICE_CHOICES = X_RAY_EXAMINATIONS + ULTRASOUND_EXAMINATIONS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lab_rate_field_map = {}
        self._radiology_rate_field_map = {}

        settings_obj = self.instance if getattr(self.instance, "pk", None) else None
        existing_lab_rates = (
            (settings_obj.lab_service_rates or {}) if settings_obj else {}
        )
        existing_radiology_rates = (
            (settings_obj.radiology_service_rates or {}) if settings_obj else {}
        )

        self.lab_rate_fields = []
        for code, label in self.LAB_SERVICE_CHOICES:
            field_name = _rate_field_name("lab_rate", code)
            self._lab_rate_field_map[field_name] = code
            initial = existing_lab_rates.get(code, DEFAULT_LAB_FEE)
            self.fields[field_name] = forms.DecimalField(
                max_digits=12,
                decimal_places=2,
                min_value=Decimal("0.00"),
                initial=initial,
                required=True,
                label=f"{label} Charge",
            )
            self.lab_rate_fields.append((label, self[field_name]))

        self.radiology_rate_fields = []
        for code, label in self.RADIOLOGY_SERVICE_CHOICES:
            field_name = _rate_field_name("radiology_rate", code)
            self._radiology_rate_field_map[field_name] = code
            fallback = (
                DEFAULT_RADIOLOGY_TYPE_RATES["xray"]
                if code.endswith("_xray")
                else DEFAULT_RADIOLOGY_TYPE_RATES["ultrasound"]
            )
            initial = existing_radiology_rates.get(code, fallback)
            self.fields[field_name] = forms.DecimalField(
                max_digits=12,
                decimal_places=2,
                min_value=Decimal("0.00"),
                initial=initial,
                required=True,
                label=f"{label} Rate",
            )
            self.radiology_rate_fields.append((label, self[field_name]))

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.FileInput):
                css = "form-control"
            elif isinstance(field.widget, forms.Select):
                css = "form-select"
            elif isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            else:
                css = "form-control"
            existing = field.widget.attrs.get("class", "").strip()
            field.widget.attrs["class"] = f"{existing} {css}".strip()

    def save(self, commit=True):
        instance = super().save(commit=False)

        lab_rates = {}
        for field_name, code in self._lab_rate_field_map.items():
            value = self.cleaned_data.get(field_name)
            if value is not None:
                lab_rates[code] = str(value)

        radiology_rates = {}
        for field_name, code in self._radiology_rate_field_map.items():
            value = self.cleaned_data.get(field_name)
            if value is not None:
                radiology_rates[code] = str(value)

        instance.lab_service_rates = lab_rates
        instance.radiology_service_rates = radiology_rates

        if commit:
            instance.save()
        return instance


class InstallationWizardForm(forms.ModelForm):
    branch_name = forms.CharField(max_length=255)
    branch_code = forms.CharField(max_length=20)
    branch_address = forms.CharField(widget=forms.Textarea)
    branch_city = forms.CharField(max_length=100)
    branch_country = forms.CharField(max_length=100, initial="Uganda")
    branch_phone = forms.CharField(max_length=30)
    branch_email = forms.EmailField()

    admin_username = forms.CharField(max_length=150)
    admin_first_name = forms.CharField(max_length=150, required=False)
    admin_last_name = forms.CharField(max_length=150, required=False)
    admin_phone = forms.CharField(max_length=30, required=False)
    admin_email = forms.EmailField()
    admin_password = forms.CharField(widget=forms.PasswordInput(render_value=True))
    admin_password_confirm = forms.CharField(
        widget=forms.PasswordInput(render_value=True)
    )

    class Meta:
        model = SystemSettings
        fields = [
            "clinic_name",
            "logo",
            "primary_color",
            "secondary_color",
            "sidebar_color",
            "sidebar_text_color",
            "sidebar_text_size",
            "dashboard_color",
            "text_color",
            "system_email",
            "timezone",
        ]
        widgets = {
            "primary_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "secondary_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_text_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "sidebar_text_size": forms.NumberInput(
                attrs={"step": "0.01", "min": "0.70", "max": "1.20"}
            ),
            "dashboard_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
            "text_color": forms.TextInput(
                attrs={"type": "color", "class": "form-control-color"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            existing = field.widget.attrs.get("class", "").strip()
            field.widget.attrs["class"] = f"{existing} {css}".strip()

        self.fields["branch_address"].widget.attrs.setdefault("rows", 3)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("admin_password")
        confirm = cleaned_data.get("admin_password_confirm")
        if password and confirm and password != confirm:
            self.add_error("admin_password_confirm", "Passwords do not match.")
        return cleaned_data

    def clean_admin_username(self):
        username = (self.cleaned_data.get("admin_username") or "").strip()
        if not username:
            return username

        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

    def clean_branch_code(self):
        branch_code = (self.cleaned_data.get("branch_code") or "").strip()
        if not branch_code:
            return branch_code

        if Branch.objects.filter(branch_code__iexact=branch_code).exists():
            raise forms.ValidationError("A branch with that code already exists.")
        return branch_code
