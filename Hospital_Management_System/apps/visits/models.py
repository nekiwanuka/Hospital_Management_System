from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BranchScopedModel


class Visit(BranchScopedModel):
    VISIT_TYPE_CHOICES = [
        ("outpatient", "Outpatient"),
        ("emergency", "Emergency"),
        ("admission", "Admission"),
    ]
    STATUS_CHOICES = [
        ("waiting_triage", "Waiting Triage"),
        ("in_triage", "In Triage"),
        ("waiting_doctor", "Waiting Doctor"),
        ("lab_requested", "Lab Requested"),
        ("radiology_requested", "Radiology Requested"),
        ("waiting_pharmacy", "Waiting Pharmacy"),
        ("billing_queue", "Billing Queue"),
        ("admission_queue", "Admission Queue"),
        ("admitted", "Admitted"),
        ("completed", "Completed"),
    ]

    visit_number = models.CharField(max_length=32, unique=True)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit_type = models.CharField(
        max_length=20, choices=VISIT_TYPE_CHOICES, default="outpatient"
    )
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default="waiting_triage"
    )
    assigned_clinician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_visits",
    )
    assigned_consultation_room = models.CharField(max_length=60, blank=True)
    check_in_time = models.DateTimeField(default=timezone.now)
    check_out_time = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "status", "check_in_time"]),
            models.Index(fields=["patient", "check_in_time"]),
        ]

    def __str__(self):
        return f"{self.visit_number} - {self.patient}"

    @property
    def is_open(self):
        return self.check_out_time is None and self.status != "completed"

    def _generate_visit_number(self):
        now = timezone.now()
        letter = "V"
        if self.branch_id and self.branch and self.branch.branch_name:
            letter = self.branch.branch_name[0].upper()
        yy = now.strftime("%y")
        mm = now.strftime("%m")
        prefix = f"V{letter}{yy}{mm}-"
        latest = (
            Visit.objects.filter(visit_number__startswith=prefix)
            .order_by("-visit_number")
            .values_list("visit_number", flat=True)
            .first()
        )
        next_num = 1
        if latest:
            try:
                next_num = int(latest.rsplit("-", 1)[-1]) + 1
            except (ValueError, IndexError):
                next_num = 1
        return f"{prefix}{next_num:04d}"

    def save(self, *args, **kwargs):
        if not self.visit_number:
            self.visit_number = self._generate_visit_number()
        if self.status == "completed" and self.check_out_time is None:
            self.check_out_time = timezone.now()
        super().save(*args, **kwargs)


class VisitQueueEvent(BranchScopedModel):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    moved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    moved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "to_status", "moved_at"]),
            models.Index(fields=["visit", "moved_at"]),
        ]

    def __str__(self):
        return f"{self.visit.visit_number}: {self.from_status} -> {self.to_status}"
