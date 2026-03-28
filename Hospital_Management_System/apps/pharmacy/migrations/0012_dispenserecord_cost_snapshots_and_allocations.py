from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0008_item_service_mapping_and_legacy_stock_backfill"),
        ("pharmacy", "0011_medicalstorerequest_item"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispenserecord",
            name="profit_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=14,
            ),
        ),
        migrations.AddField(
            model_name="dispenserecord",
            name="total_cost_snapshot",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=14,
            ),
        ),
        migrations.AddField(
            model_name="dispenserecord",
            name="unit_cost_snapshot",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0.0000"),
                max_digits=14,
            ),
        ),
        migrations.CreateModel(
            name="DispenseBatchAllocation",
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
                ("quantity", models.PositiveIntegerField()),
                (
                    "unit_cost_snapshot",
                    models.DecimalField(decimal_places=4, max_digits=14),
                ),
                (
                    "unit_price_snapshot",
                    models.DecimalField(decimal_places=2, max_digits=14),
                ),
                ("total_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("total_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacy_dispense_allocations",
                        to="inventory.batch",
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacy_dispensebatchallocation_set",
                        to="branches.branch",
                    ),
                ),
                (
                    "dispense_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allocations",
                        to="pharmacy.dispenserecord",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacy_dispense_allocations",
                        to="inventory.item",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "indexes": [
                    models.Index(
                        fields=["branch", "dispense_record"],
                        name="pharmacy_di_branch__a39ce6_idx",
                    ),
                    models.Index(
                        fields=["branch", "item", "created_at"],
                        name="pharmacy_di_branch__ecbc20_idx",
                    ),
                    models.Index(
                        fields=["branch", "batch", "created_at"],
                        name="pharmacy_di_branch__0b55d8_idx",
                    ),
                ],
            },
        ),
    ]
