from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_add_access_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="radiology_unit_assignment",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "General Radiology Queue"),
                    ("xray", "X-Ray Unit"),
                    ("ultrasound", "Ultrasound Unit"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
