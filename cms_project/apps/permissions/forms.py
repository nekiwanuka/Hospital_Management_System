from django import forms

from apps.accounts.models import User
from apps.permissions.models import UserModulePermission


class UserModulePermissionForm(forms.ModelForm):
    class Meta:
        model = UserModulePermission
        fields = [
            "user",
            "module_name",
            "can_view",
            "can_create",
            "can_update",
            "can_soft_delete",
            "can_hard_delete",
            "is_active",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            if isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            field.widget.attrs["class"] = css

        self.fields["user"].queryset = User.objects.order_by("username")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("can_hard_delete") and not cleaned.get("can_soft_delete"):
            self.add_error(
                "can_hard_delete",
                "Hard delete requires soft delete permission to be enabled.",
            )
        return cleaned
