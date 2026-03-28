from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settingsapp", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="systemsettings",
            old_name="clinic_logo",
            new_name="logo",
        ),
        migrations.RenameField(
            model_name="systemsettings",
            old_name="color_scheme",
            new_name="primary_color",
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="secondary_color",
            field=models.CharField(default="#16a085", max_length=32),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="system_email",
            field=models.EmailField(default="system@clinic.local", max_length=254),
        ),
        migrations.AddField(
            model_name="systemsettings",
            name="timezone",
            field=models.CharField(default="UTC", max_length=64),
        ),
        migrations.RemoveField(
            model_name="systemsettings",
            name="clinic_address",
        ),
        migrations.RemoveField(
            model_name="systemsettings",
            name="clinic_phone",
        ),
        migrations.RemoveField(
            model_name="systemsettings",
            name="theme",
        ),
    ]
