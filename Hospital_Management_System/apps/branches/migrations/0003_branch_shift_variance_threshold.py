from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("branches", "0002_remove_branch_date_created"),
    ]

    operations = [
        migrations.AddField(
            model_name="branch",
            name="shift_variance_threshold",
            field=models.DecimalField(decimal_places=2, default=5000, max_digits=12),
        ),
    ]
