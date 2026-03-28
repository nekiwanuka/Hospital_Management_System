from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("branches", "0002_remove_branch_date_created"),
        (
            "billing",
            "0010_rename_billing_app_branch__9bde95_idx_billing_app_branch__809baa_idx_and_more",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CashierShiftSession",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("opening_float", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("pending_approval", "Pending Approval"),
                            ("closed", "Closed"),
                        ],
                        default="open",
                        max_length=20,
                    ),
                ),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "declared_cash_total",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True
                    ),
                ),
                (
                    "expected_cash_total",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                (
                    "variance_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                (
                    "variance_threshold",
                    models.DecimalField(
                        decimal_places=2,
                        default=getattr(
                            settings, "CASHIER_SHIFT_VARIANCE_THRESHOLD_DEFAULT", 5000
                        ),
                        max_digits=12,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="branches.branch",
                    ),
                ),
                (
                    "closed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cashier_shift_closed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "opened_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cashier_shift_opened",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="cashier_shift",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="approval_requests",
                to="billing.cashiershiftsession",
            ),
        ),
        migrations.AlterField(
            model_name="approvalrequest",
            name="approval_type",
            field=models.CharField(
                choices=[
                    ("paid_rollback", "Paid Status Rollback"),
                    ("void_invoice", "Void Invoice"),
                    ("refund", "Refund"),
                    ("discount_override", "Discount Override"),
                    ("reopen_day", "Reopen Day"),
                    ("shift_variance", "Shift Variance Approval"),
                ],
                max_length=40,
            ),
        ),
        migrations.AddIndex(
            model_name="cashiershiftsession",
            index=models.Index(
                fields=["branch", "opened_by", "status"],
                name="billing_cas_branch__7c32b0_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="cashiershiftsession",
            index=models.Index(
                fields=["branch", "status", "created_at"],
                name="billing_cas_branch__8cb955_idx",
            ),
        ),
    ]
