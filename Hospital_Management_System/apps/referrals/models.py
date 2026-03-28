from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class Referral(BranchScopedModel):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="referrals",
    )
    referring_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    facility_name = models.CharField(max_length=255)
    reason = models.TextField()
    referral_date = models.DateField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "referral_date"])]

    def __str__(self):
        return f"{self.patient} -> {self.facility_name}"
