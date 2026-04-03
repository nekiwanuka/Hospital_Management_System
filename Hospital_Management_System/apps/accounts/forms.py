from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.models import User
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
