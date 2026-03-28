from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("branches", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="branch",
            name="date_created",
        ),
    ]
