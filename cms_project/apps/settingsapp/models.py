from django.db import models
from apps.core.models import TimeStampedModel


class SystemSettings(TimeStampedModel):
    clinic_name = models.CharField(max_length=255)
    logo = models.ImageField(upload_to="branding/", null=True, blank=True)
    primary_color = models.CharField(max_length=32, default="#125ea8")
    secondary_color = models.CharField(max_length=32, default="#16a085")
    sidebar_color = models.CharField(max_length=32, default="#1e293b")
    sidebar_text_color = models.CharField(max_length=32, default="#94a3b8")
    sidebar_text_size = models.DecimalField(
        max_digits=3, decimal_places=2, default=0.81
    )
    dashboard_color = models.CharField(max_length=32, default="#f1f5f9")
    text_color = models.CharField(max_length=32, default="#1e293b")
    system_email = models.EmailField()
    timezone = models.CharField(max_length=64, default="UTC")
    consultation_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=50000
    )
    lab_service_rates = models.JSONField(default=dict, blank=True)
    radiology_service_rates = models.JSONField(default=dict, blank=True)
    is_initialized = models.BooleanField(default=False)

    def __str__(self):
        return self.clinic_name
