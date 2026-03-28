from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        (
            "pharmacy",
            "0007_dispenserecord_sale_type_dispenserecord_walk_in_name_and_more",
        ),
        (
            "visits",
            "0002_rename_visits_visi_branch__eb95ff_idx_visits_visi_branch__6ac241_idx_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="PharmacyRequest",
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
                ("quantity", models.PositiveIntegerField(default=1)),
                (
                    "unit_price_snapshot",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("dispensed", "Dispensed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="requested",
                        max_length=20,
                    ),
                ),
                ("date_requested", models.DateTimeField(auto_now_add=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="branches.branch",
                    ),
                ),
                (
                    "medicine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="pharmacy.medicine",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="patients.patient",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacy_requests_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "visit",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacy_requests",
                        to="visits.visit",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="pharmacyrequest",
            index=models.Index(
                fields=["branch", "status", "date_requested"],
                name="pharmacy_ph_branch__ba1297_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="pharmacyrequest",
            index=models.Index(
                fields=["branch", "patient", "date_requested"],
                name="pharmacy_ph_branch__a018f6_idx",
            ),
        ),
    ]
