from django.conf import settings
from django.db import models
from decimal import Decimal
from django.utils import timezone

from apps.core.models import BranchScopedModel


X_RAY_EXAMINATIONS = [
    ("chest_xray", "Chest X-ray"),
    ("skull_xray", "Skull X-ray"),
    ("spine_xray", "Spine X-ray"),
    ("pelvic_xray", "Pelvic X-ray"),
    ("hand_xray", "Hand X-ray"),
    ("leg_xray", "Leg X-ray"),
    ("knee_xray", "Knee X-ray"),
    ("foot_xray", "Foot X-ray"),
    ("abdominal_xray", "Abdominal X-ray"),
]

ULTRASOUND_EXAMINATIONS = [
    ("abdominal_ultrasound", "Abdominal ultrasound"),
    ("pelvic_ultrasound", "Pelvic ultrasound"),
    ("obstetric_ultrasound", "Obstetric ultrasound"),
    ("kidney_ultrasound", "Kidney ultrasound"),
    ("prostate_ultrasound", "Prostate ultrasound"),
    ("breast_ultrasound", "Breast ultrasound"),
    ("thyroid_ultrasound", "Thyroid ultrasound"),
    ("doppler_ultrasound", "Doppler ultrasound"),
]

EXAMINATION_LABELS = dict(X_RAY_EXAMINATIONS + ULTRASOUND_EXAMINATIONS)

BODY_REGION_BY_EXAMINATION = {
    "chest_xray": "Chest",
    "skull_xray": "Skull",
    "spine_xray": "Spine",
    "pelvic_xray": "Pelvis",
    "hand_xray": "Hand",
    "leg_xray": "Leg",
    "knee_xray": "Knee",
    "foot_xray": "Foot",
    "abdominal_xray": "Abdomen",
    "abdominal_ultrasound": "Abdomen",
    "pelvic_ultrasound": "Pelvis",
    "obstetric_ultrasound": "Obstetric",
    "kidney_ultrasound": "Kidneys",
    "prostate_ultrasound": "Prostate",
    "breast_ultrasound": "Breast",
    "thyroid_ultrasound": "Thyroid",
    "doppler_ultrasound": "Vascular",
}


class RadiologyType(BranchScopedModel):
    IMAGING_TYPE_CHOICES = [
        ("xray", "X-Ray"),
        ("ultrasound", "Ultrasound"),
    ]

    imaging_type = models.CharField(max_length=20, choices=IMAGING_TYPE_CHOICES)
    examination_code = models.CharField(max_length=60)
    examination_name = models.CharField(max_length=120)
    body_region = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_types"
        indexes = [
            models.Index(fields=["branch", "imaging_type", "is_active"]),
            models.Index(fields=["branch", "body_region"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "examination_code"],
                name="radiology_unique_exam_code_per_branch",
            )
        ]

    def __str__(self):
        return f"{self.get_imaging_type_display()} - {self.examination_name}"


class ImagingRequest(BranchScopedModel):
    IMAGING_TYPE_CHOICES = [
        ("xray", "X-Ray"),
        ("ultrasound", "Ultrasound"),
    ]

    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("scheduled", "Scheduled"),
        ("patient_arrived", "Patient Arrived"),
        ("scanning", "Scanning"),
        ("reporting", "Reporting"),
        ("completed", "Completed"),
    ]

    PRIORITY_CHOICES = [
        ("normal", "Normal"),
        ("urgent", "Urgent"),
    ]

    request_identifier = models.CharField(max_length=40, unique=True, blank=True)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT)
    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="imaging_requests",
    )
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    imaging_type = models.CharField(max_length=30, choices=IMAGING_TYPE_CHOICES)
    requested_department = models.CharField(max_length=120, blank=True)
    specific_examination = models.CharField(max_length=120, blank=True)
    body_region = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="requested"
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default="normal"
    )
    clinical_notes = models.TextField(blank=True)
    symptoms = models.TextField(blank=True)
    suspected_condition = models.TextField(blank=True)
    additional_notes = models.TextField(blank=True)
    unit_cost_snapshot = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost_snapshot = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    profit_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    last_menstrual_period = models.DateField(null=True, blank=True)
    pregnancy_weeks = models.PositiveIntegerField(null=True, blank=True)
    date_requested = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_requests"
        indexes = [
            models.Index(fields=["branch", "request_identifier"]),
            models.Index(fields=["branch", "imaging_type", "status", "date_requested"]),
        ]

    def __str__(self):
        return f"{self.request_identifier or self.pk} - {self.patient}"

    @property
    def examination_label(self):
        return EXAMINATION_LABELS.get(
            self.specific_examination, self.specific_examination
        )

    @property
    def patient_age(self):
        if not self.patient or not self.patient.date_of_birth:
            return None
        today = timezone.localdate()
        dob = self.patient.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def save(self, *args, **kwargs):
        if not self.request_identifier:
            branch_code = (
                self.branch.branch_code if self.branch_id and self.branch else "RAD"
            )[:6]
            prefix = f"{branch_code}-RAD-"
            latest = (
                ImagingRequest.objects.filter(request_identifier__startswith=prefix)
                .order_by("-request_identifier")
                .values_list("request_identifier", flat=True)
                .first()
            )
            next_num = 1
            if latest:
                try:
                    next_num = int(latest.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    next_num = 1
            self.request_identifier = f"{prefix}{next_num:06d}"

        if self.specific_examination and not self.body_region:
            self.body_region = BODY_REGION_BY_EXAMINATION.get(
                self.specific_examination, self.body_region
            )

        if not self.clinical_notes:
            notes = []
            if self.symptoms:
                notes.append(f"Symptoms: {self.symptoms}")
            if self.suspected_condition:
                notes.append(f"Suspected condition: {self.suspected_condition}")
            if self.additional_notes:
                notes.append(f"Additional notes: {self.additional_notes}")
            self.clinical_notes = "\n".join(notes)

        super().save(*args, **kwargs)


class RadiologyQueue(BranchScopedModel):
    imaging_request = models.OneToOneField(
        ImagingRequest, on_delete=models.CASCADE, related_name="queue_entry"
    )
    status = models.CharField(
        max_length=20,
        choices=ImagingRequest.STATUS_CHOICES,
        default="requested",
    )
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_radiology_queue_entries",
    )
    scheduled_for = models.DateTimeField(null=True, blank=True)
    patient_arrived_at = models.DateTimeField(null=True, blank=True)
    scan_started_at = models.DateTimeField(null=True, blank=True)
    reporting_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_queue"
        indexes = [
            models.Index(fields=["branch", "status", "scheduled_for"]),
            models.Index(fields=["branch", "completed_at"]),
        ]

    def __str__(self):
        return f"Queue {self.imaging_request.request_identifier} - {self.status}"


class ImagingResult(BranchScopedModel):
    imaging_request = models.OneToOneField(
        ImagingRequest, on_delete=models.CASCADE, related_name="result"
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="imaging_results_as_technician",
    )
    radiologist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="imaging_results_as_radiologist",
    )
    machine_used = models.CharField(max_length=120, blank=True)
    examination = models.TextField(blank=True)
    clinical_information = models.TextField(blank=True)
    report = models.TextField(blank=True)
    findings = models.TextField(blank=True)
    impression = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    image_file = models.FileField(upload_to="radiology/scans/", blank=True, null=True)
    report_file = models.FileField(
        upload_to="radiology/reports/", blank=True, null=True
    )
    date_performed = models.DateTimeField(blank=True, null=True)
    date_reported = models.DateTimeField(blank=True, null=True)
    notified_requesting_doctor_at = models.DateTimeField(blank=True, null=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_reports"
        indexes = [models.Index(fields=["branch", "date_performed", "date_reported"])]

    def __str__(self):
        return f"Result for {self.imaging_request}"

    @property
    def summary_result(self):
        return self.impression or self.findings or self.report


class RadiologyImage(BranchScopedModel):
    FILE_KIND_CHOICES = [
        ("dicom", "DICOM"),
        ("image", "Image"),
        ("pdf", "PDF Report"),
        ("clip", "Ultrasound Clip"),
    ]

    imaging_request = models.ForeignKey(
        ImagingRequest, on_delete=models.CASCADE, related_name="images"
    )
    image_file = models.FileField(
        upload_to="radiology/attachments/", blank=True, null=True
    )
    report_file = models.FileField(
        upload_to="radiology/reports/", blank=True, null=True
    )
    file_kind = models.CharField(
        max_length=20, choices=FILE_KIND_CHOICES, default="image"
    )
    caption = models.CharField(max_length=255, blank=True)
    machine_used = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_radiology_images",
    )
    upload_date = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_images"
        indexes = [
            models.Index(fields=["branch", "file_kind", "upload_date"]),
            models.Index(fields=["imaging_request", "upload_date"]),
        ]

    def __str__(self):
        return f"Attachment for {self.imaging_request.request_identifier}"


class RadiologyComparison(BranchScopedModel):
    current_request = models.ForeignKey(
        ImagingRequest,
        on_delete=models.CASCADE,
        related_name="comparison_current_request_set",
    )
    previous_request = models.ForeignKey(
        ImagingRequest,
        on_delete=models.CASCADE,
        related_name="comparison_previous_request_set",
    )
    compared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="radiology_comparisons_made",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        db_table = "radiology_comparisons"
        indexes = [
            models.Index(fields=["branch", "created_at"]),
            models.Index(fields=["current_request", "previous_request"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["current_request", "previous_request"],
                name="radiology_unique_request_comparison",
            )
        ]

    def __str__(self):
        return (
            f"Compare {self.previous_request.request_identifier} -> "
            f"{self.current_request.request_identifier}"
        )


class RadiologyNotification(BranchScopedModel):
    EVENT_CHOICES = [
        ("scan_completed", "Scan Completed"),
        ("report_uploaded", "Report Uploaded"),
    ]

    imaging_request = models.ForeignKey(
        ImagingRequest, on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="radiology_notifications",
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "recipient", "is_read", "created_at"]),
            models.Index(fields=["branch", "event_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.recipient} - {self.get_event_type_display()}"
