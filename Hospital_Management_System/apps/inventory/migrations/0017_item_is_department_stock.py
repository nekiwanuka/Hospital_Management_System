from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0016_batch_location_batch_selling_price_override_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="is_department_stock",
            field=models.BooleanField(
                default=False,
                help_text="True for stock received by a department (not store inventory).",
            ),
        ),
    ]
