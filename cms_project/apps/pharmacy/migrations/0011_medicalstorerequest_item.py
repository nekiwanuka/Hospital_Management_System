from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_batch_pack_size_units_batch_packs_received_and_more"),
        ("pharmacy", "0010_medicine_inventory_item"),
    ]

    operations = [
        migrations.AddField(
            model_name="medicalstorerequest",
            name="item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="medical_store_requests",
                to="inventory.item",
            ),
        ),
    ]
