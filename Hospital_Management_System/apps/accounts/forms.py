from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.models import User, ShiftSecretCode
from apps.permissions.models import UserModulePermission


def _sync_module_permissions(user, modules, granter=None):
    """Ensure UserModulePermission rows exist for every module the admin
    selected, and deactivate rows for modules that were removed."""
    current = set(
        UserModulePermission.objects.filter(user=user).values_list(
            "module_name", flat=True
        )
    )
    granted = set(modules)

    # Create or reactivate permissions for newly granted modules
    for mod in granted:
        perm, created = UserModulePermission.objects.get_or_create(
            user=user,
            module_name=mod,
            defaults={
                "can_view": True,
                "can_create": True,
                "can_update": True,
                "is_active": True,
                "granted_by": granter,
                "notes": "Granted via user admin form",
            },
        )
        if not created and not perm.is_active:
            perm.is_active = True
            perm.granted_by = granter
            perm.notes = "Re-activated via user admin form"
            perm.save(update_fields=["is_active", "granted_by", "notes"])

    # Deactivate permissions for modules removed from the list
    removed = current - granted
    if removed:
        UserModulePermission.objects.filter(user=user, module_name__in=removed).update(
            is_active=False
        )


class UserEditForm(forms.ModelForm):
    """Edit an existing user (no password fields)."""

    allowed_modules = forms.MultipleChoiceField(
        choices=User.MODULE_ACCESS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        required=False,
        label="Module Access",
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "radiology_unit_assignment",
            "branch",
            "is_active",
            "can_view_revenue",
            "can_delete_records",
            "can_approve_edits",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            effective = self.instance.allowed_modules
            if not effective:
                effective = User.ROLE_DEFAULT_MODULES.get(self.instance.role, [])
            self.fields["allowed_modules"].initial = effective or []
        self.fields["radiology_unit_assignment"].help_text = (
            "Used only for radiology technicians to send them straight to X-ray or ultrasound after login."
        )
        for field_name, field in self.fields.items():
            if field_name == "allowed_modules":
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            field.widget.attrs["class"] = css

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.allowed_modules = self.cleaned_data.get("allowed_modules", [])
        if commit:
            instance.save()
            _sync_module_permissions(instance, instance.allowed_modules)
        return instance


class UserCreateForm(UserCreationForm):
    allowed_modules = forms.MultipleChoiceField(
        choices=User.MODULE_ACCESS_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        required=False,
        label="Module Access",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
            "radiology_unit_assignment",
            "branch",
            "is_active",
            "can_view_revenue",
            "can_delete_records",
            "can_approve_edits",
            "password1",
            "password2",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default: give new user the receptionist role's default modules
        self.fields["allowed_modules"].initial = User.ROLE_DEFAULT_MODULES.get(
            "receptionist", [code for code, _ in User.MODULE_ACCESS_CHOICES]
        )
        self.fields["radiology_unit_assignment"].help_text = (
            "Used only for radiology technicians to send them straight to X-ray or ultrasound after login."
        )
        for field_name, field in self.fields.items():
            if field_name == "allowed_modules":
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            field.widget.attrs["class"] = css

            if field_name == "password1":
                field.help_text = "Use at least 8 characters."
            if field_name == "password2":
                field.help_text = "Enter the same password for confirmation."

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.allowed_modules = self.cleaned_data.get("allowed_modules", [])
        if commit:
            instance.save()
            _sync_module_permissions(instance, instance.allowed_modules)
        return instance


class OpenShiftForm(forms.Form):
    """Form that staff fill out to open a shift."""

    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Your full name"}
        ),
        label="Full Name",
    )
    title = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. Pharmacist, Cashier"}
        ),
        label="Title / Role",
    )
    secret_code = forms.CharField(
        max_length=8,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Enter your secret code"}
        ),
        label="Secret Code",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_secret_code(self):
        code = self.cleaned_data["secret_code"].strip().upper()
        try:
            secret = ShiftSecretCode.objects.get(user=self.user)
        except ShiftSecretCode.DoesNotExist:
            raise forms.ValidationError(
                "No secret code has been assigned to your account. Contact your system administrator."
            )
        if secret.code != code:
            raise forms.ValidationError("Invalid secret code.")
        return code


class CloseShiftForm(forms.Form):
    """Optional notes when closing a shift."""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Shift handover notes (optional)",
            }
        ),
        label="Handover Notes",
    )


class AssignSecretCodeForm(forms.Form):
    """Admin form to assign or regenerate a secret code for a user."""

    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Staff Member",
    )
