from django.db import migrations, models
import django.db.models.deletion


def backfill_invoice_date(apps, schema_editor):
    Invoice = apps.get_model("billing", "Invoice")
    for invoice in Invoice.objects.filter(date__isnull=True):
        invoice.date = invoice.created_at
        invoice.save(update_fields=["date"])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="date",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.RunPython(backfill_invoice_date, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="invoice",
            name="date",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.CreateModel(
            name="InvoiceLineItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "service_type",
                    models.CharField(
                        choices=[
                            ("consultation", "Consultation"),
                            ("lab", "Lab Test"),
                            ("radiology", "Radiology Scan"),
                            ("pharmacy", "Pharmacy Medicine"),
                        ],
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(max_length=255)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("source_model", models.CharField(max_length=40)),
                ("source_id", models.PositiveIntegerField()),
                (
                    "branch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="branches.branch",
                    ),
                ),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="line_items",
                        to="billing.invoice",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_model", "source_id"),
                        name="billing_unique_source_item",
                    )
                ]
            },
        ),
        migrations.AddIndex(
            model_name="invoicelineitem",
            index=models.Index(
                fields=["branch", "service_type"],
                name="billing_inv_branch__b166f8_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoicelineitem",
            index=models.Index(
                fields=["source_model", "source_id"],
                name="billing_inv_source__c4b6ad_idx",
            ),
        ),
    ]
