from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("referrals", "0001_initial"),
    ]

    operations = [
        migrations.RenameField(
            model_name="referral",
            old_name="referred_facility",
            new_name="facility_name",
        ),
    ]
