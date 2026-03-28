from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "inventory",
            "0011_rename_inventory_i_branch__e56a4d_idx_inventory_i_branch__e1a46e_idx_and_more",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="item",
            name="store_department",
            field=models.CharField(
                choices=[
                    ("pharmacy", "Pharmacy Store"),
                    ("laboratory", "Laboratory Store"),
                    ("xray", "X-Ray Store"),
                    ("ultrasound", "Ultrasound Store"),
                    ("radiology", "Radiology Store"),
                    ("general", "General Store"),
                ],
                default="pharmacy",
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="inventorystoreprofile",
            name="store_department",
            field=models.CharField(
                choices=[
                    ("pharmacy", "Pharmacy Store"),
                    ("laboratory", "Laboratory Store"),
                    ("xray", "X-Ray Store"),
                    ("ultrasound", "Ultrasound Store"),
                    ("radiology", "Radiology Store"),
                    ("general", "General Store"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="serviceconsumption",
            name="reversed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="serviceconsumption",
            name="reversed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="reversed_service_consumptions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="serviceconsumption",
            name="reversal_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="serviceconsumption",
            name="reversal_reference",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddIndex(
            model_name="serviceconsumption",
            index=models.Index(
                fields=["branch", "reversed_at"],
                name="inventory_s_branch__d24f4f_idx",
            ),
        ),
    ]
