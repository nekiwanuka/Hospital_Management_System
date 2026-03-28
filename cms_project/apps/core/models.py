from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BranchScopedModel(TimeStampedModel):
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)

    class Meta(TimeStampedModel.Meta):
        abstract = True


class AuditLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    branch = models.ForeignKey(
        "branches.Branch", on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64, blank=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["branch", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} - {self.object_type}"


class DeleteRequest(TimeStampedModel):
    """
    Any user can request deletion of a record. The director reviews and
    soft-deletes; the system admin can then permanently delete.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Soft-Deleted"),
        ("deleted", "Permanently Deleted"),
        ("rejected", "Rejected"),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="delete_requests_made",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delete_requests_reviewed",
    )
    branch = models.ForeignKey("branches.Branch", on_delete=models.CASCADE)
    object_type = models.CharField(max_length=100)
    object_id = models.PositiveIntegerField()
    object_label = models.CharField(max_length=255, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewer_notes = models.TextField(blank=True)

    class Meta(TimeStampedModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return (
            f"Delete {self.object_type} #{self.object_id} — {self.get_status_display()}"
        )
