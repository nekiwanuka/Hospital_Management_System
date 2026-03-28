from django.conf import settings
from django.db import models
from apps.core.models import BranchScopedModel


class TriageRecord(BranchScopedModel):
    OUTCOME_CHOICES = [
        ("send_to_doctor", "Send to doctor"),
        ("emergency", "Emergency"),
        ("admission", "Admission"),
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
    temperature = models.DecimalField(max_digits=5, decimal_places=2)
    blood_pressure = models.CharField(max_length=20)
    pulse_rate = models.PositiveIntegerField()
    respiratory_rate = models.PositiveIntegerField()
    oxygen_level = models.PositiveIntegerField()
    weight = models.DecimalField(max_digits=6, decimal_places=2)
    height = models.DecimalField(max_digits=6, decimal_places=2)
    symptoms = models.TextField()
    triage_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT
    )
    date = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "date"])]

    def __str__(self):
        return f"{self.visit_number} - {self.patient}"

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
        super().save(*args, **kwargs)
