from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("laboratory", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(
            model_name="labrequest",
            old_name="sample_taken",
            new_name="sample_collected",
        ),
        migrations.AddField(
            model_name="labrequest",
            name="technician",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="lab_requests_handled",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="labrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("requested", "Requested"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("reviewed", "Reviewed"),
                ],
                default="requested",
                max_length=20,
            ),
        ),
    ]
