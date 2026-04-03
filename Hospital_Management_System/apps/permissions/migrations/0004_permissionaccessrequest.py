from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        (
            "permissions",
            "0003_rename_permission_m_module__77f822_idx_permissions_module__77f034_idx_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="PermissionAccessRequest",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "module_name",
                    models.CharField(
                        choices=[
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
                        ],
                        max_length=40,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("reviewer_notes", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="permission_requests_reviewed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="permission_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["status", "created_at"],
                        name="permissions_access_status_idx",
                    ),
                    models.Index(
                        fields=["user", "module_name"],
                        name="permissions_access_user_mod_idx",
                    ),
                ],
            },
        ),
    ]
