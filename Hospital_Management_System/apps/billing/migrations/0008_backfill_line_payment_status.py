from django.db import migrations, models


def backfill_line_payment_status(apps, schema_editor):
    InvoiceLineItem = apps.get_model("billing", "InvoiceLineItem")

    paid_qs = InvoiceLineItem.objects.filter(invoice__payment_status="paid")
    paid_qs.update(paid_amount=models.F("amount"), payment_status="paid")

    partial_qs = InvoiceLineItem.objects.filter(
        invoice__payment_status="partial",
        payment_status="pending",
    )
    partial_qs.update(payment_status="partial")


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0007_cashdrawer_invoicelineitem_paid_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_line_payment_status, migrations.RunPython.noop),
    ]
