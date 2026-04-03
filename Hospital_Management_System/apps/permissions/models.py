from django.conf import settings
from django.db import models
from django.utils import timezone


class UserModulePermission(models.Model):
    MODULE_CHOICES = [
        ("patients", "Patients"),
        ("triage", "Triage"),
        ("consultation", "Consultation"),
        ("laboratory", "Laboratory"),
        ("radiology", "Radiology"),
        ("pharmacy", "Pharmacy"),
        ("billing", "Billing"),
        ("admission", "Admission"),
        ("emergency", "Emergency"),
        ("referrals", "Referrals"),
        ("inventory", "Inventory"),
        ("visits", "Visits"),
        ("reports", "Reports"),
        ("accounts", "Accounts"),
        ("permissions", "Permissions"),
        ("branches", "Branches"),
        ("settingsapp", "System Settings"),
        ("core", "Core Dashboards"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    module_name = models.CharField(max_length=40, choices=MODULE_CHOICES)
    can_view = models.BooleanField(default=True)
    can_create = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_soft_delete = models.BooleanField(default=False)
    can_hard_delete = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="module_permission_grants",
    )
    granted_at = models.DateTimeField(auto_now=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("user", "module_name")]
        indexes = [
            models.Index(fields=["module_name"]),
            models.Index(fields=["user", "module_name"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.module_name}"

    @property
    def can_delete_any(self):
        return self.can_soft_delete or self.can_hard_delete


class PermissionAccessRequest(models.Model):
    """A user requests access to a module they cannot reach."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="permission_requests",
    )
    module_name = models.CharField(
        max_length=40, choices=UserModulePermission.MODULE_CHOICES
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="permission_requests_reviewed",
    )
    reviewer_notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "module_name"]),
        ]

    def __str__(self):
        return (
            f"{self.user.username} → {self.get_module_name_display()} ({self.status})"
        )
