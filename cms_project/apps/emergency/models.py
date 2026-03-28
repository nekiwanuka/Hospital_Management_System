from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class EmergencyCase(BranchScopedModel):
    EMERGENCY_LEVEL_CHOICES = [
        ("critical", "Critical"),
        ("high", "High"),
        ("moderate", "Moderate"),
        ("low", "Low"),
    ]

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="emergency_cases",
    )
    emergency_level = models.CharField(
        max_length=20, choices=EMERGENCY_LEVEL_CHOICES, default="high"
    )
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    treatment = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(
                fields=["branch", "date"], name="emergency_e_branch__5db6c4_idx"
            )
        ]

    def __str__(self):
        return f"{self.patient} - {self.get_emergency_level_display()}"
