from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        (
            "visits",
            "0002_rename_visits_visi_branch__eb95ff_idx_visits_visi_branch__6ac241_idx_and_more",
        ),
        ("laboratory", "0002_lab_workflow_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="labrequest",
            name="visit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lab_requests",
                to="visits.visit",
            ),
        ),
    ]
