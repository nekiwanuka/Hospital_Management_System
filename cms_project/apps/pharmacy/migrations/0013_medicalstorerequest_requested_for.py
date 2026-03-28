from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0012_dispenserecord_cost_snapshots_and_allocations"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicalstorerequest",
            name="requested_for",
            field=models.CharField(
                choices=[
                    ("pharmacy", "Pharmacy Store"),
                    ("laboratory", "Laboratory Store"),
                    ("radiology", "Radiology Store"),
                ],
                default="pharmacy",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="medicalstorerequest",
            index=models.Index(
                fields=["branch", "requested_for", "status"],
                name="pharmacy_me_branch__781f16_idx",
            ),
        ),
    ]
