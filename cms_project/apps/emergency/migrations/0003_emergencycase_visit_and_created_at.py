from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        (
            "visits",
            "0002_rename_visits_visi_branch__eb95ff_idx_visits_visi_branch__6ac241_idx_and_more",
        ),
        ("emergency", "0002_emergency_fields_refactor"),
    ]

    operations = [
        migrations.AddField(
            model_name="emergencycase",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="emergencycase",
            name="visit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="emergency_cases",
                to="visits.visit",
            ),
        ),
    ]
