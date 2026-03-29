from django.db import migrations, models
from decimal import Decimal


def backfill_amount_paid(apps, schema_editor):
    Invoice = apps.get_model("billing", "Invoice")
    InvoiceLineItem = apps.get_model("billing", "InvoiceLineItem")
    for invoice in Invoice.objects.all():
        total_paid = InvoiceLineItem.objects.filter(invoice=invoice).aggregate(
            total=models.Sum("paid_amount")
        ).get("total") or Decimal("0.00")
        if total_paid > 0:
            invoice.amount_paid = total_paid
            invoice.save(update_fields=["amount_paid"])
        elif invoice.payment_status == "paid":
            invoice.amount_paid = invoice.total_amount
            invoice.save(update_fields=["amount_paid"])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0016_add_amount_paid_to_invoice"),
    ]

    operations = [
        migrations.RunPython(backfill_amount_paid, migrations.RunPython.noop),
    ]
