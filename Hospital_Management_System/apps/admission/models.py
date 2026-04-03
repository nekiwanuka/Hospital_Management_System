from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class Ward(BranchScopedModel):
    """Hospital ward / unit."""

    WARD_TYPES = [
        ("general", "General"),
        ("maternity", "Maternity"),
        ("paediatric", "Paediatric"),
        ("icu", "ICU"),
        ("surgical", "Surgical"),
        ("emergency", "Emergency"),
        ("private", "Private"),
    ]
    name = models.CharField(max_length=120)
    ward_type = models.CharField(max_length=20, choices=WARD_TYPES, default="general")
    floor = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        unique_together = [("branch", "name")]

    def __str__(self):
        return self.name

    @property
    def total_beds(self):
        return self.beds.count()

    @property
    def available_beds(self):
        return self.beds.filter(status="available").count()


class Bed(BranchScopedModel):
    """Individual bed within a ward."""

    STATUS_CHOICES = [
        ("available", "Available"),
        ("occupied", "Occupied"),
        ("maintenance", "Under Maintenance"),
        ("reserved", "Reserved"),
    ]
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name="beds")
    bed_number = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="available"
    )

    class Meta(BranchScopedModel.Meta):
        unique_together = [("ward", "bed_number")]
        ordering = ["ward", "bed_number"]

    def __str__(self):
        return f"{self.ward.name} – {self.bed_number}"


class Admission(BranchScopedModel):
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="admissions",
    )
    ward = models.CharField(max_length=100, blank=True)
    bed = models.CharField(max_length=40, blank=True)
    bed_assigned = models.ForeignKey(
        Bed,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admissions",
    )
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


class VitalSign(BranchScopedModel):
    """Structured vital signs record for admitted patients."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.CASCADE,
        related_name="vital_signs",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vital_sign_recordings",
    )
    temperature = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Temperature in °C",
    )
    blood_pressure_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_pressure_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    pulse_rate = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Beats per minute"
    )
    respiratory_rate = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Breaths per minute"
    )
    oxygen_saturation = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="SpO2 %"
    )
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["admission", "-created_at"])]

    def __str__(self):
        return f"Vitals for {self.admission.patient} at {self.created_at:%d %b %H:%M}"

    @property
    def blood_pressure(self):
        if self.blood_pressure_systolic and self.blood_pressure_diastolic:
            return f"{self.blood_pressure_systolic}/{self.blood_pressure_diastolic}"
        return "—"
