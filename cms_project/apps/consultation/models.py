from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class Consultation(BranchScopedModel):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consultations",
    )
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    consultation_room = models.CharField(max_length=60, default="Consultation Room 1")
    symptoms = models.TextField()
    diagnosis = models.TextField()
    treatment_plan = models.TextField()
    prescription = models.TextField(blank=True)
    lab_tests_requested = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["branch", "created_at"])]
