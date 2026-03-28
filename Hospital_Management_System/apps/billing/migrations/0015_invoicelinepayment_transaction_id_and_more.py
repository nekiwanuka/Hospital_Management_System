from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0014_add_post_payment_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoicelinepayment",
            name="transaction_id",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="receipt",
            name="transaction_id",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
