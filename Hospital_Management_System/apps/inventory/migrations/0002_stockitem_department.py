from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockitem",
            name="department",
            field=models.CharField(
                choices=[
                    ("general", "General"),
                    ("laboratory", "Laboratory"),
                    ("radiology", "Radiology"),
                    ("pharmacy", "Pharmacy"),
                    ("admission", "Admission"),
                ],
                default="general",
                max_length=30,
            ),
        ),
        migrations.AddIndex(
            model_name="stockitem",
            index=models.Index(
                fields=["branch", "department"],
                name="inventory_s_branch__f37fc3_idx",
            ),
        ),
    ]
