from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0013_alter_approvalrequest_approval_type_receipt"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("paid", "Paid"),
                    ("partial", "Partial"),
                    ("post_payment", "Post Payment"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
