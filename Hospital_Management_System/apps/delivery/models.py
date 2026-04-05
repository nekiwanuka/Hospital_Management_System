from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class DeliveryRecord(BranchScopedModel):
    DELIVERY_TYPES = [
        ("normal", "Normal Vaginal Delivery"),
        ("caesarean", "Caesarean Section"),
        ("assisted", "Assisted Delivery (Vacuum/Forceps)"),
        ("breech", "Breech Delivery"),
    ]
    OUTCOMES = [
        ("live_birth", "Live Birth"),
        ("still_birth", "Still Birth"),
        ("neonatal_death", "Neonatal Death"),
    ]
    BABY_GENDER = [
        ("male", "Male"),
        ("female", "Female"),
        ("ambiguous", "Ambiguous"),
    ]
    STATUS_CHOICES = [
        ("admitted", "Admitted to Labour Ward"),
        ("in_labour", "In Labour"),
        ("delivered", "Delivered"),
        ("post_delivery", "Post-Delivery Observation"),
        ("discharged", "Discharged"),
    ]

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    admission = models.ForeignKey(
        "admission.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )

    # Labour info
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="admitted")
    admitted_at = models.DateTimeField(auto_now_add=True)
    labour_started_at = models.DateTimeField(null=True, blank=True)
    delivery_datetime = models.DateTimeField(null=True, blank=True)
    delivery_type = models.CharField(max_length=20, choices=DELIVERY_TYPES, blank=True)

    # Baby details
    baby_gender = models.CharField(max_length=10, choices=BABY_GENDER, blank=True)
    baby_weight_kg = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Baby weight in kilograms",
    )
    apgar_score_1min = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="APGAR at 1 min (0-10)"
    )
    apgar_score_5min = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="APGAR at 5 min (0-10)"
    )
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True)

    # Clinical
    gravida = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Number of pregnancies"
    )
    parity = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Number of previous deliveries"
    )
    gestational_age_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    complications = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Staff
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deliveries_performed",
    )
    midwife = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries_assisted",
    )

    discharge_datetime = models.DateTimeField(null=True, blank=True)
    discharge_notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-admitted_at"]
        indexes = [
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["branch", "admitted_at"]),
            models.Index(fields=["patient", "-admitted_at"]),
        ]

    def __str__(self):
        return f"Delivery #{self.pk} - {self.patient}"


class BabyRecord(BranchScopedModel):
    BABY_GENDER = [
        ("male", "Male"),
        ("female", "Female"),
        ("ambiguous", "Ambiguous"),
    ]
    OUTCOMES = [
        ("live_birth", "Live Birth"),
        ("still_birth", "Still Birth"),
        ("neonatal_death", "Neonatal Death"),
    ]

    delivery = models.ForeignKey(
        DeliveryRecord,
        on_delete=models.CASCADE,
        related_name="babies",
    )
    birth_order = models.PositiveSmallIntegerField(
        default=1, help_text="1 for single/first twin, 2 for second twin, etc."
    )
    baby_name = models.CharField(
        max_length=100, blank=True, help_text="Optional baby name"
    )
    gender = models.CharField(max_length=10, choices=BABY_GENDER, blank=True)
    weight_kg = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Baby weight in kilograms",
    )
    apgar_score_1min = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="APGAR at 1 min (0-10)"
    )
    apgar_score_5min = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="APGAR at 5 min (0-10)"
    )
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True)
    head_circumference_cm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Head circumference in cm",
    )
    length_cm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Baby length in cm",
    )
    resuscitation_needed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["birth_order"]
        indexes = [
            models.Index(fields=["delivery", "birth_order"]),
        ]

    def __str__(self):
        name = self.baby_name or f"Baby {self.birth_order}"
        return f"{name} — Delivery #{self.delivery_id}"


class DeliveryNote(BranchScopedModel):
    NOTE_CATEGORIES = [
        ("labour_progress", "Labour Progress"),
        ("vitals", "Vitals"),
        ("medication", "Medication"),
        ("observation", "Observation"),
        ("handover", "Shift Handover"),
    ]

    delivery = models.ForeignKey(
        DeliveryRecord,
        on_delete=models.CASCADE,
        related_name="delivery_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="authored_delivery_notes",
    )
    category = models.CharField(
        max_length=20, choices=NOTE_CATEGORIES, default="observation"
    )
    note = models.TextField()

    class Meta(BranchScopedModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["delivery", "-created_at"])]

    def __str__(self):
        return f"Note by {self.author} on {self.created_at:%d %b %Y %H:%M}"
