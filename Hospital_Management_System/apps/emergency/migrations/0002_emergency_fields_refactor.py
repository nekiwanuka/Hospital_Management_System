from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("emergency", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="emergencycase",
            old_name="assigned_doctor",
            new_name="doctor",
        ),
        migrations.RenameField(
            model_name="emergencycase",
            old_name="emergency_treatment",
            new_name="treatment",
        ),
        migrations.RenameField(
            model_name="emergencycase",
            old_name="created_at",
            new_name="date",
        ),
        migrations.AlterModelOptions(
            name="emergencycase",
            options={
                "indexes": [
                    models.Index(
                        fields=["branch", "date"],
                        name="emergency_e_branch__5db6c4_idx",
                    )
                ]
            },
        ),
        migrations.RemoveField(
            model_name="emergencycase",
            name="patient_name",
        ),
        migrations.AddField(
            model_name="emergencycase",
            name="emergency_level",
            field=models.CharField(
                choices=[
                    ("critical", "Critical"),
                    ("high", "High"),
                    ("moderate", "Moderate"),
                    ("low", "Low"),
                ],
                default="high",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="emergencycase",
            name="patient",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="patients.patient",
            ),
        ),
    ]
