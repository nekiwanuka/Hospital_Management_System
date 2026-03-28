from django.db import models
from apps.core.models import TimeStampedModel


class Branch(TimeStampedModel):
    STATUS_CHOICES = [("active", "Active"), ("inactive", "Inactive")]

    branch_name = models.CharField(max_length=255)
    branch_code = models.CharField(max_length=20, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    shift_variance_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=5000,
    )

    class Meta(TimeStampedModel.Meta):
        ordering = ["branch_name"]

    def __str__(self):
        return f"{self.branch_name} ({self.branch_code})"
