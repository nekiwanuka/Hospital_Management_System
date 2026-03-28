from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("permissions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="usermodulepermission",
            name="can_create",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="usermodulepermission",
            name="can_update",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="usermodulepermission",
            name="can_view",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="usermodulepermission",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="usermodulepermission",
            name="notes",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
