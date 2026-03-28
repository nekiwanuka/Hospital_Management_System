from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("consultation", "0002_consultation_visit"),
    ]

    operations = [
        migrations.AddField(
            model_name="consultation",
            name="consultation_room",
            field=models.CharField(default="Consultation Room 1", max_length=60),
        ),
    ]
