from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_batch_pack_size_units_batch_packs_received_and_more"),
        (
            "pharmacy",
            "0009_rename_pharmacy_ph_branch__ba1297_idx_pharmacy_ph_branch__4ed316_idx_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="medicine",
            name="inventory_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pharmacy_medicines",
                to="inventory.item",
            ),
        ),
        migrations.AddIndex(
            model_name="medicine",
            index=models.Index(
                fields=["branch", "inventory_item"],
                name="pharmacy_me_branch__11f183_idx",
            ),
        ),
    ]
