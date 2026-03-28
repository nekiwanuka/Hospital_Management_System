from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0013_medicalstorerequest_requested_for"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicalstorerequest",
            name="requested_unit",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "General"),
                    ("xray", "X-Ray Unit"),
                    ("ultrasound", "Ultrasound Unit"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="medicalstorerequest",
            index=models.Index(
                fields=["branch", "requested_for", "requested_unit", "status"],
                name="pharmacy_me_branch__a7b7f8_idx",
            ),
        ),
    ]
