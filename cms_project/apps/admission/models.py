from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class Admission(BranchScopedModel):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admissions",
    )
    ward = models.CharField(max_length=100)
    bed = models.CharField(max_length=40)
    admission_date = models.DateTimeField(auto_now_add=True)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admission_doctor",
    )
    nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admission_nurse",
    )
    diagnosis = models.TextField()
    discharge_date = models.DateTimeField(null=True, blank=True)
    discharge_summary = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "admission_date"])]


class NursingNote(BranchScopedModel):
    admission = models.ForeignKey(
        Admission,
        on_delete=models.CASCADE,
        related_name="nursing_notes",
    )
    nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="nursing_notes",
    )
    NOTE_CATEGORIES = [
        ("general", "General Observation"),
        ("vitals", "Vitals Update"),
        ("medication", "Medication Administration"),
        ("wound_care", "Wound Care"),
        ("intake_output", "Intake / Output"),
        ("handover", "Shift Handover"),
    ]
    category = models.CharField(
        max_length=20, choices=NOTE_CATEGORIES, default="general"
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["admission", "-created_at"])]

    def __str__(self):
        return f"Note by {self.nurse} on {self.created_at:%d %b %Y %H:%M}"
