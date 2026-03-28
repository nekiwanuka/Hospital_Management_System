from django.db import migrations, models
import django.db.models.deletion


def backfill_item_store_department(apps, schema_editor):
    Item = apps.get_model("inventory", "Item")
    Item.objects.filter(service_type="lab").update(store_department="laboratory")
    Item.objects.filter(service_type="radiology").update(store_department="radiology")
    Item.objects.exclude(service_type__in=["lab", "radiology"]).update(
        store_department="pharmacy"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0008_item_service_mapping_and_legacy_stock_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="store_department",
            field=models.CharField(
                choices=[
                    ("pharmacy", "Pharmacy Store"),
                    ("laboratory", "Laboratory Store"),
                    ("radiology", "Radiology Store"),
                    ("general", "General Store"),
                ],
                default="pharmacy",
                max_length=30,
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["branch", "store_department"],
                name="inventory_i_branch__0ed3ec_idx",
            ),
        ),
        migrations.CreateModel(
            name="ServiceConsumption",
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
                (
                    "service_type",
                    models.CharField(
                        choices=[
                            ("consultation", "Consultation"),
                            ("lab", "Laboratory Service"),
                            ("radiology", "Radiology Service"),
                        ],
                        max_length=20,
                    ),
                ),
                ("service_code", models.CharField(max_length=120)),
                ("source_model", models.CharField(max_length=40)),
                ("source_id", models.PositiveIntegerField()),
                ("quantity", models.PositiveIntegerField()),
                (
                    "unit_cost_snapshot",
                    models.DecimalField(decimal_places=4, max_digits=14),
                ),
                ("total_cost", models.DecimalField(decimal_places=2, max_digits=14)),
                ("reference", models.CharField(blank=True, max_length=180)),
                ("consumed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="service_consumptions",
                        to="inventory.batch",
                    ),
                ),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_serviceconsumption_set",
                        to="branches.branch",
                    ),
                ),
                (
                    "consumed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="service_consumptions",
                        to="accounts.user",
                    ),
                ),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="service_consumptions",
                        to="inventory.item",
                    ),
                ),
            ],
            options={
                "abstract": False,
                "indexes": [
                    models.Index(
                        fields=["branch", "service_type", "consumed_at"],
                        name="inventory_s_branch__ef63a2_idx",
                    ),
                    models.Index(
                        fields=["branch", "source_model", "source_id"],
                        name="inventory_s_branch__65751c_idx",
                    ),
                    models.Index(
                        fields=["branch", "item", "consumed_at"],
                        name="inventory_s_branch__8310b9_idx",
                    ),
                    models.Index(
                        fields=["branch", "batch", "consumed_at"],
                        name="inventory_s_branch__3c08d0_idx",
                    ),
                ],
            },
        ),
        migrations.RunPython(backfill_item_store_department, migrations.RunPython.noop),
    ]
