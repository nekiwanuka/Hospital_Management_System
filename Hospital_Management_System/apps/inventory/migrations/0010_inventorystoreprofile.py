from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0009_item_store_department_serviceconsumption"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InventoryStoreProfile",
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
                    "store_department",
                    models.CharField(
                        choices=[
                            ("pharmacy", "Pharmacy Store"),
                            ("laboratory", "Laboratory Store"),
                            ("radiology", "Radiology Store"),
                            ("general", "General Store"),
                        ],
                        max_length=30,
                    ),
                ),
                ("location", models.CharField(blank=True, max_length=255)),
                ("notes", models.TextField(blank=True)),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="branches.branch",
                    ),
                ),
                (
                    "manager",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="managed_inventory_stores",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.AddIndex(
            model_name="inventorystoreprofile",
            index=models.Index(
                fields=["branch", "store_department"],
                name="inventory_i_branch__e56a4d_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="inventorystoreprofile",
            constraint=models.UniqueConstraint(
                fields=("branch", "store_department"),
                name="inventory_unique_store_profile_per_branch",
            ),
        ),
    ]
