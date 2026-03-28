from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("laboratory", "0003_labrequest_visit"),
    ]

    operations = [
        migrations.AddField(
            model_name="labrequest",
            name="profit_amount",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=14
            ),
        ),
        migrations.AddField(
            model_name="labrequest",
            name="total_cost_snapshot",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=14
            ),
        ),
        migrations.AddField(
            model_name="labrequest",
            name="unit_cost_snapshot",
            field=models.DecimalField(
                decimal_places=4, default=Decimal("0.0000"), max_digits=14
            ),
        ),
    ]
