from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class TriageRecord(BranchScopedModel):
    OUTCOME_CHOICES = [
        ("send_to_doctor", "Send to doctor"),
        ("emergency", "Emergency"),
        ("admission", "Admission"),
    ]
    PRIORITY_CHOICES = [
        (1, "Normal"),
        (2, "Low concern"),
        (3, "Moderate"),
        (4, "High"),
        (5, "Critical"),
    ]
    BLOOD_GROUP_CHOICES = [
        ("", "Unknown"),
        ("A+", "A+"),
        ("A-", "A−"),
        ("B+", "B+"),
        ("B-", "B−"),
        ("AB+", "AB+"),
        ("AB-", "AB−"),
        ("O+", "O+"),
        ("O-", "O−"),
    ]

    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="triage_records",
    )
    visit_number = models.CharField(max_length=32)
    temperature = models.DecimalField(max_digits=5, decimal_places=2, help_text="°C")
    blood_pressure = models.CharField(max_length=20, help_text="mmHg (e.g. 120/80)")
    pulse_rate = models.PositiveIntegerField(help_text="bpm")
    respiratory_rate = models.PositiveIntegerField(help_text="breaths/min")
    oxygen_level = models.PositiveIntegerField(help_text="SpO₂ %")
    weight = models.DecimalField(max_digits=6, decimal_places=2, help_text="kg")
    height = models.DecimalField(max_digits=6, decimal_places=2, help_text="cm")
    blood_group = models.CharField(
        max_length=5, blank=True, default="", choices=BLOOD_GROUP_CHOICES
    )
    symptoms = models.TextField()
    auto_notes = models.TextField("Clinical Auto-Notes", blank=True)
    priority_score = models.PositiveSmallIntegerField(
        choices=PRIORITY_CHOICES, default=1
    )
    triage_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    date = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "date"])]

    def __str__(self):
        return f"{self.visit_number} - {self.patient}"

    # ------------------------------------------------------------------
    # Clinical analysis helpers
    # ------------------------------------------------------------------
    def _parse_bp(self):
        """Return (systolic, diastolic) or (None, None)."""
        try:
            parts = self.blood_pressure.replace(" ", "").split("/")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError, AttributeError):
            return None, None

    @property
    def bmi(self):
        try:
            h_m = float(self.height) / 100
            if h_m > 0:
                return round(float(self.weight) / (h_m * h_m), 1)
        except (TypeError, ZeroDivisionError):
            pass
        return None

    def calculate_priority_and_notes(self):
        """Analyse vitals and return (priority_score, auto_notes_text)."""
        notes = []
        score = 1  # start at normal

        # Temperature (°C)
        temp = float(self.temperature) if self.temperature else None
        if temp is not None:
            if temp >= 39.5:
                notes.append(f"HIGH FEVER ({temp}°C) — consider urgent evaluation")
                score = max(score, 5)
            elif temp >= 38.0:
                notes.append(f"Fever ({temp}°C)")
                score = max(score, 3)
            elif temp < 35.0:
                notes.append(f"Hypothermia ({temp}°C)")
                score = max(score, 4)

        # Blood pressure
        sys, dia = self._parse_bp()
        if sys is not None:
            if sys >= 180 or dia >= 120:
                notes.append(f"HYPERTENSIVE CRISIS (BP {self.blood_pressure} mmHg)")
                score = max(score, 5)
            elif sys >= 140 or dia >= 90:
                notes.append(f"Hypertension (BP {self.blood_pressure} mmHg)")
                score = max(score, 3)
            elif sys < 90 or dia < 60:
                notes.append(f"Hypotension (BP {self.blood_pressure} mmHg)")
                score = max(score, 4)

        # Pulse rate (bpm)
        if self.pulse_rate:
            if self.pulse_rate > 120:
                notes.append(f"Severe tachycardia ({self.pulse_rate} bpm)")
                score = max(score, 4)
            elif self.pulse_rate > 100:
                notes.append(f"Tachycardia ({self.pulse_rate} bpm)")
                score = max(score, 3)
            elif self.pulse_rate < 50:
                notes.append(f"Severe bradycardia ({self.pulse_rate} bpm)")
                score = max(score, 4)
            elif self.pulse_rate < 60:
                notes.append(f"Bradycardia ({self.pulse_rate} bpm)")
                score = max(score, 2)

        # Respiratory rate (breaths/min)
        if self.respiratory_rate:
            if self.respiratory_rate > 30:
                notes.append(f"Severe tachypnea ({self.respiratory_rate} breaths/min)")
                score = max(score, 5)
            elif self.respiratory_rate > 20:
                notes.append(f"Tachypnea ({self.respiratory_rate} breaths/min)")
                score = max(score, 3)
            elif self.respiratory_rate < 8:
                notes.append(f"Bradypnea ({self.respiratory_rate} breaths/min)")
                score = max(score, 4)

        # Oxygen saturation (SpO₂ %)
        if self.oxygen_level is not None:
            if self.oxygen_level < 90:
                notes.append(f"SEVERE HYPOXEMIA (SpO₂ {self.oxygen_level}%)")
                score = max(score, 5)
            elif self.oxygen_level < 95:
                notes.append(f"Hypoxemia (SpO₂ {self.oxygen_level}%)")
                score = max(score, 4)

        # BMI
        bmi_val = self.bmi
        if bmi_val is not None:
            if bmi_val < 16:
                notes.append(f"Severely underweight (BMI {bmi_val})")
                score = max(score, 3)
            elif bmi_val < 18.5:
                notes.append(f"Underweight (BMI {bmi_val})")
            elif bmi_val >= 35:
                notes.append(f"Obese class II+ (BMI {bmi_val})")
                score = max(score, 2)
            elif bmi_val >= 30:
                notes.append(f"Obese (BMI {bmi_val})")

        if not notes:
            notes.append("All vitals within normal range.")

        return score, "\n".join(notes)

    def _generate_visit_number(self):
        # Keep visit numbers in the format VIS-000001 and increment globally.
        next_num = 1
        recent_visit_numbers = TriageRecord.objects.filter(
            visit_number__startswith="VIS-"
        ).values_list("visit_number", flat=True)

        max_num = 0
        for visit_number in recent_visit_numbers:
            suffix = visit_number.removeprefix("VIS-")
            if suffix.isdigit():
                value = int(suffix)
                if value > max_num:
                    max_num = value

        if max_num:
            next_num = max_num + 1

        candidate = f"VIS-{next_num:06d}"
        while TriageRecord.objects.filter(visit_number=candidate).exists():
            next_num += 1
            candidate = f"VIS-{next_num:06d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.visit_number:
            self.visit_number = self._generate_visit_number()
        # Auto-analyse vitals before saving
        self.priority_score, self.auto_notes = self.calculate_priority_and_notes()
        super().save(*args, **kwargs)
