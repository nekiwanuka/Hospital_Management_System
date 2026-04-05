import secrets

from django.contrib.auth.models import Group
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone


class User(AbstractUser):
    ROLE_CHOICES = [
        ("director", "Director"),
        ("system_admin", "System Administrator"),
        ("doctor", "Doctor"),
        ("nurse", "Nurse"),
        ("triage_officer", "Triage Officer"),
        ("lab_technician", "Laboratory Technician"),
        ("radiology_technician", "Radiology Technician"),
        ("radiologist", "Radiologist"),
        ("pharmacist", "Pharmacist"),
        ("cashier", "Cashier"),
        ("receptionist", "Receptionist"),
    ]

    MODULE_ACCESS_CHOICES = [
        ("patients", "Patients"),
        ("visits", "Visits Queue"),
        ("triage", "Triage"),
        ("consultation", "Consultation"),
        ("emergency", "Emergency"),
        ("admission", "Admission"),
        ("delivery", "Delivery Ward"),
        ("laboratory", "Laboratory"),
        ("radiology", "Radiology"),
        ("pharmacy", "Pharmacy"),
        ("inventory", "Inventory"),
        ("billing", "Billing"),
        ("reports", "Reports"),
        ("referrals", "Referrals"),
    ]

    RADIOLOGY_UNIT_ASSIGNMENT_CHOICES = [
        ("", "General Radiology Queue"),
        ("xray", "X-Ray Unit"),
        ("ultrasound", "Ultrasound Unit"),
    ]

    # Default module access per role. Admin/director/superuser bypass this entirely.
    ROLE_DEFAULT_MODULES = {
        "doctor": [
            "patients",
            "visits",
            "consultation",
            "triage",
            "laboratory",
            "radiology",
            "pharmacy",
            "admission",
            "delivery",
            "emergency",
            "referrals",
        ],
        "nurse": [
            "patients",
            "visits",
            "triage",
            "consultation",
            "admission",
            "delivery",
            "emergency",
            "pharmacy",
        ],
        "triage_officer": [
            "patients",
            "visits",
            "triage",
            "emergency",
        ],
        "lab_technician": [
            "patients",
            "visits",
            "laboratory",
        ],
        "radiology_technician": [
            "patients",
            "visits",
            "radiology",
        ],
        "radiologist": [
            "patients",
            "visits",
            "radiology",
        ],
        "pharmacist": [
            "patients",
            "visits",
            "pharmacy",
            "inventory",
        ],
        "cashier": [
            "patients",
            "visits",
            "billing",
        ],
        "receptionist": [
            "patients",
            "visits",
            "triage",
            "consultation",
            "emergency",
            "billing",
            "reports",
        ],
    }

    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=40, choices=ROLE_CHOICES, default="receptionist")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT)

    # Access controls
    allowed_modules = models.JSONField(default=list, blank=True)
    can_view_revenue = models.BooleanField(default=False)
    can_delete_records = models.BooleanField(default=False)
    can_approve_edits = models.BooleanField(default=False)
    radiology_unit_assignment = models.CharField(
        max_length=20,
        choices=RADIOLOGY_UNIT_ASSIGNMENT_CHOICES,
        blank=True,
        default="",
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    @property
    def can_view_all_branches(self):
        return self.role in {"director", "system_admin"} or self.is_superuser

    def has_module_access(self, module_name):
        """Check if user can access a given module."""
        if self.is_superuser or self.role in ("system_admin", "director"):
            return True
        # Explicit allowed_modules override defaults
        modules = self.allowed_modules
        if modules:
            if module_name in modules:
                return True
        else:
            # Fall back to role defaults
            defaults = self.ROLE_DEFAULT_MODULES.get(self.role)
            if defaults is not None:
                if module_name in defaults:
                    return True
            else:
                return True
        # Check for an explicit permission grant (even if module not in role defaults)
        try:
            from apps.permissions.models import UserModulePermission

            return UserModulePermission.objects.filter(
                user=self, module_name=module_name, is_active=True, can_view=True
            ).exists()
        except Exception:
            return False

    def get_effective_modules(self):
        """Return the list of module codes this user can actually access."""
        if self.is_superuser or self.role in ("system_admin", "director"):
            return [code for code, _ in self.MODULE_ACCESS_CHOICES]
        if self.allowed_modules:
            base = list(self.allowed_modules)
        else:
            defaults = self.ROLE_DEFAULT_MODULES.get(self.role)
            if defaults is not None:
                base = list(defaults)
            else:
                return [code for code, _ in self.MODULE_ACCESS_CHOICES]
        # Merge in explicitly granted modules
        try:
            from apps.permissions.models import UserModulePermission

            granted = UserModulePermission.objects.filter(
                user=self, is_active=True, can_view=True
            ).values_list("module_name", flat=True)
            for mod in granted:
                if mod not in base:
                    base.append(mod)
        except Exception:
            pass
        return base

    def clean(self):
        super().clean()
        if self.branch_id is None:
            raise ValidationError({"branch": "Branch assignment is required."})
        if self.role != "radiology_technician":
            self.radiology_unit_assignment = ""
        elif self.radiology_unit_assignment not in {
            choice for choice, _ in self.RADIOLOGY_UNIT_ASSIGNMENT_CHOICES
        }:
            raise ValidationError(
                {"radiology_unit_assignment": "Choose a valid radiology landing unit."}
            )

    def _sync_role_group(self):
        role_names = {role for role, _ in self.ROLE_CHOICES}
        target_group = Group.objects.filter(name=self.role).first()
        existing_role_groups = self.groups.filter(name__in=role_names)

        for group in existing_role_groups:
            if not target_group or group.id != target_group.id:
                self.groups.remove(group)
        if target_group and not self.groups.filter(id=target_group.id).exists():
            self.groups.add(target_group)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        try:
            self._sync_role_group()
        except (OperationalError, ProgrammingError):
            pass


class ShiftSecretCode(models.Model):
    """
    A secret code assigned by the system admin to each user.
    The user must enter this code when opening a shift.
    """

    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="shift_secret",
    )
    code = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shift Secret Code"
        verbose_name_plural = "Shift Secret Codes"

    def __str__(self):
        return f"Secret code for {self.user.get_full_name() or self.user.username}"

    @staticmethod
    def generate_code():
        """Generate a random 6-character alphanumeric code."""
        return secrets.token_hex(3).upper()  # 6 hex chars


class Shift(models.Model):
    """
    Tracks when a user opens and closes their work shift.
    A user must have an open shift to access the system.
    """

    STATUS_CHOICES = [
        ("open", "Open"),
        ("closed", "Closed"),
    ]

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="shifts",
    )
    branch = models.ForeignKey(
        "branches.Branch",
        on_delete=models.PROTECT,
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["branch", "opened_at"]),
        ]

    def __str__(self):
        return f"Shift #{self.pk} — {self.user.username} ({self.status})"

    @property
    def duration(self):
        end = self.closed_at or timezone.now()
        return end - self.opened_at

    @property
    def duration_display(self):
        d = self.duration
        total_seconds = int(d.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours}h {minutes}m"
