from django.db import migrations, models
import django.db.models.deletion


def backfill_user_branch(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Branch = apps.get_model("branches", "Branch")

    default_branch = Branch.objects.order_by("id").first()
    if default_branch is None:
        default_branch = Branch.objects.create(
            branch_name="Default Branch",
            branch_code="DEFAULT",
            address="N/A",
            city="N/A",
            country="N/A",
            phone="N/A",
            email="default@local.test",
            status="active",
        )

    User.objects.filter(branch__isnull=True).update(branch=default_branch)


class Migration(migrations.Migration):
    dependencies = [
        ("branches", "0002_remove_branch_date_created"),
        ("accounts", "0002_user_phone_alter_user_role"),
    ]

    operations = [
        migrations.RunPython(backfill_user_branch, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="branch",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="branches.branch",
            ),
        ),
    ]
