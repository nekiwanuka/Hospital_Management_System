"""
Billing service helpers.

The key function for the post-payment authorization workflow is
``add_post_payment_line_for_admitted``.  It is called from the consultation
module whenever a doctor orders a service (pharmacy / lab / radiology) for an
admitted patient so the charge appears immediately on the running credit
invoice and the cashier can authorise it.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem


def _find_or_create_post_payment_invoice(branch, patient, visit, user):
    """Return the active post_payment invoice for this patient/visit,
    creating one if none exists."""
    invoice = (
        Invoice.objects.filter(
            branch=branch,
            patient=patient,
            visit=visit,
            payment_status="post_payment",
        )
        .order_by("-created_at")
        .first()
    )
    if invoice:
        return invoice

    from apps.billing.views import _generate_invoice_number

    return Invoice.objects.create(
        branch=branch,
        invoice_number=_generate_invoice_number(branch),
        patient=patient,
        visit=visit,
        services="Post-payment charges (admitted patient)",
        total_amount=Decimal("0.00"),
        payment_method="cash",
        payment_status="post_payment",
        invoice_category="inpatient",
        cashier=user,
    )


@transaction.atomic
def add_post_payment_line_for_admitted(
    *,
    branch,
    patient,
    visit,
    user,
    service_type,
    description,
    amount,
    source_model,
    source_id,
    unit_cost=None,
    total_cost=None,
    profit_amount=None,
):
    """Add an *unauthorized* line item to the patient's post-payment invoice.

    The cashier must later authorise it from the billing dashboard before the
    downstream department (pharmacy / lab / radiology) can act on it.

    Returns the created ``InvoiceLineItem``.
    """
    if unit_cost is None:
        unit_cost = Decimal("0.00")
    if total_cost is None:
        total_cost = Decimal("0.00")
    if profit_amount is None:
        profit_amount = amount - total_cost

    invoice = _find_or_create_post_payment_invoice(branch, patient, visit, user)

    line = InvoiceLineItem.objects.create(
        invoice=invoice,
        branch=branch,
        service_type=service_type,
        description=description,
        amount=amount,
        paid_amount=Decimal("0.00"),
        payment_status="pending",
        unit_cost=unit_cost,
        total_cost=total_cost,
        profit_amount=profit_amount,
        source_model=source_model,
        source_id=source_id,
        cashier_authorized=False,
    )

    invoice.total_amount = invoice.total_amount + amount
    svc_line = f"\n{description} – {amount}"
    invoice.services = (invoice.services or "") + svc_line
    invoice.save(update_fields=["total_amount", "services", "updated_at"])

    return line
