from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pharmacy", "0014_medicalstorerequest_requested_unit"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicalstorerequest",
            name="decision_remarks",
            field=models.TextField(blank=True),
        ),
    ]