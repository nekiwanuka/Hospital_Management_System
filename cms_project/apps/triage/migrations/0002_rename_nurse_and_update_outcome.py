from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("triage", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="triagerecord",
            old_name="nurse",
            new_name="triage_officer",
        ),
        migrations.AlterField(
            model_name="triagerecord",
            name="outcome",
            field=models.CharField(
                choices=[
                    ("send_to_doctor", "Send to doctor"),
                    ("emergency", "Emergency"),
                    ("admission", "Admission"),
                ],
                max_length=32,
            ),
        ),
    ]
