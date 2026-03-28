from django import forms

from apps.core.permissions import branch_queryset_for_user
from apps.patients.models import Patient
from apps.visits.models import Visit


class VisitCreateForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ["patient", "visit_type"]

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "form-select"
            field.widget.attrs["class"] = css

        if user is not None:
            self.fields["patient"].queryset = branch_queryset_for_user(
                user, Patient.objects.order_by("last_name", "first_name")
            )
