from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

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

    WARD_CATEGORIES = [
        ("ordinary", "Ordinary"),
        ("vip", "VIP"),
        ("vvip", "VVIP"),
    ]

    name = models.CharField(max_length=120)
    ward_type = models.CharField(max_length=20, choices=WARD_TYPES, default="general")
    ward_category = models.CharField(
        max_length=10, choices=WARD_CATEGORIES, default="ordinary"
    )
    daily_rate = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Daily bed charge for this ward (set from Settings).",
    )
    floor = models.CharField(max_length=40, blank=True)
    capacity = models.PositiveIntegerField(default=0, help_text="Planned bed capacity")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        unique_together = [("branch", "name")]

    def __str__(self):
        cat = self.get_ward_category_display()
        return f"{self.name} ({cat})"

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
    ward_obj = models.ForeignKey(
        Ward,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admissions",
        help_text="Links to the Ward for billing rate lookup.",
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
    last_billed_date = models.DateField(
        null=True,
        blank=True,
        help_text="The last date a daily ward charge was billed for.",
    )

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "admission_date"])]

    @property
    def is_active(self):
        return self.discharge_date is None

    @property
    def days_admitted(self):
        end = self.discharge_date or timezone.now()
        delta = end - self.admission_date
        return max(delta.days, 1)

    @property
    def daily_rate(self):
        if self.ward_obj:
            return self.ward_obj.daily_rate
        return Decimal("0.00")

    @property
    def running_ward_charges(self):
        return self.daily_rate * self.days_admitted


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


class AdmissionDailyCharge(BranchScopedModel):
    """One row per day a ward charge is billed to an admitted patient."""

    admission = models.ForeignKey(
        Admission,
        on_delete=models.CASCADE,
        related_name="daily_charges",
    )
    charge_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    ward_category = models.CharField(max_length=10, choices=Ward.WARD_CATEGORIES)
    invoice_line = models.ForeignKey(
        "billing.InvoiceLineItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_charges",
    )

    class Meta(BranchScopedModel.Meta):
        unique_together = [("admission", "charge_date")]
        ordering = ["-charge_date"]

    def __str__(self):
        return f"{self.admission.patient} – {self.charge_date} – {self.amount}"
