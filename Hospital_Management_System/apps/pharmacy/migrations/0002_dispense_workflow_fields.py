from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_dispensed_by(apps, schema_editor):
    DispenseRecord = apps.get_model("pharmacy", "DispenseRecord")
    User = apps.get_model("accounts", "User")

    default_user = User.objects.order_by("id").first()
    if default_user:
        DispenseRecord.objects.filter(dispensed_by__isnull=True).update(
            dispensed_by=default_user
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_backfill_and_require_branch"),
        ("pharmacy", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispenserecord",
            name="dispensed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dispensed_records",
                to="accounts.user",
            ),
        ),
        migrations.AddField(
            model_name="dispenserecord",
            name="prescribed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="prescribed_dispenses",
                to="accounts.user",
            ),
        ),
        migrations.AddField(
            model_name="dispenserecord",
            name="prescription_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="dispenserecord",
            name="unit_price",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=12
            ),
        ),
        migrations.RunPython(backfill_dispensed_by, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dispenserecord",
            name="dispensed_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dispensed_records",
                to="accounts.user",
            ),
        ),
        migrations.AddIndex(
            model_name="dispenserecord",
            index=models.Index(
                fields=["branch", "dispensed_at"], name="pharmacy_di_branch__89dd31_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="dispenserecord",
            index=models.Index(
                fields=["branch", "patient", "dispensed_at"],
                name="pharmacy_di_branch__e4f7dc_idx",
            ),
        ),
    ]
