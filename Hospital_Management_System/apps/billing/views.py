import csv
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.dateparse import parse_date
from django.utils import timezone
from urllib.parse import urlencode

from apps.billing.forms import InvoiceForm, InvoicePaymentForm, LineItemPaymentForm
from apps.billing.models import (
    ApprovalRequest,
    CashierShiftSession,
    CashDrawer,
    FinancialSequenceAnomaly,
    Invoice,
    InvoiceLineItem,
    InvoiceLinePayment,
    Receipt,
)
from apps.branches.models import Branch
from apps.consultation.models import Consultation
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.laboratory.models import LabRequest
from apps.inventory.services import allocate_service_stock, service_stock_cost
from apps.pharmacy.models import DispenseRecord, PharmacyRequest
from apps.pharmacy.services import sync_branch_medicine_catalog
from apps.patients.models import Patient
from apps.radiology.models import ImagingRequest
from apps.referrals.models import Referral
from apps.core.models import AuditLog
from apps.settingsapp.services import (
    get_consultation_fee,
    get_lab_fee,
    get_radiology_fee,
)
from apps.visits.models import Visit
from apps.visits.services import transition_visit


REFERRAL_FEE = Decimal("20000.00")
DEFAULT_SHIFT_VARIANCE_THRESHOLD = Decimal("5000.00")


def _safe_return_url(request):
    return_to = (
        request.GET.get("return_to") or request.POST.get("return_to") or ""
    ).strip()
    if not return_to or not return_to.startswith("/"):
        return ""
    if not url_has_allowed_host_and_scheme(
        return_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return ""
    return return_to


def _url_with_return_to(base_url, return_to):
    if not return_to:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'return_to': return_to})}"


def _redirect_with_return_to(base_url, return_to):
    return redirect(_url_with_return_to(base_url, return_to))


def _log_financial_event(
    request,
    *,
    action,
    object_type,
    object_id,
    before=None,
    after=None,
    reason="",
):
    details = {
        "path": request.path,
        "method": request.method,
        "before": before or {},
        "after": after or {},
    }
    if reason:
        details["reason"] = reason

    try:
        AuditLog.objects.create(
            user=request.user,
            branch=getattr(request, "branch", None)
            or getattr(request.user, "branch", None),
            action=action,
            object_type=object_type,
            object_id=str(object_id),
            details=str(details),
            ip_address=(
                request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
                if request.META.get("HTTP_X_FORWARDED_FOR")
                else request.META.get("REMOTE_ADDR")
            ),
        )
    except Exception:
        pass


def _get_open_shift_for_user(user):
    if not getattr(user, "branch_id", None):
        return None
    return (
        CashierShiftSession.objects.filter(
            branch_id=user.branch_id,
            opened_by=user,
            status="open",
        )
        .order_by("-created_at")
        .first()
    )


def _expected_cash_for_shift(shift):
    totals = InvoiceLinePayment.objects.filter(
        branch=shift.branch,
        received_by=shift.opened_by,
        payment_method="cash",
        paid_at__gte=shift.created_at,
    )
    if shift.closed_at:
        totals = totals.filter(paid_at__lte=shift.closed_at)
    return totals.aggregate(total=Sum("amount_paid")).get("total") or Decimal("0.00")


def _create_paid_rollback_request(
    request,
    *,
    invoice,
    new_status,
    payment_method,
    reason,
):
    existing = ApprovalRequest.objects.filter(
        branch=invoice.branch,
        approval_type="paid_rollback",
        invoice=invoice,
        status="pending",
    ).first()
    if existing:
        return existing, False

    approval_request = ApprovalRequest.objects.create(
        branch=invoice.branch,
        approval_type="paid_rollback",
        invoice=invoice,
        requested_by=request.user,
        from_status=invoice.payment_status,
        to_status=new_status,
        requested_payment_method=payment_method,
        reason=reason,
    )
    return approval_request, True


def _get_or_create_drawer(branch, service_type):
    label = dict(InvoiceLineItem.SERVICE_TYPES).get(service_type, service_type.title())
    drawer, _ = CashDrawer.objects.get_or_create(
        branch=branch,
        service_type=service_type,
        defaults={"drawer_name": f"{label} Cashier Point", "is_active": True},
    )
    return drawer


def _require_transaction_id(payment_method, transaction_id):
    transaction_id = (transaction_id or "").strip()
    if payment_method != "cash" and not transaction_id:
        raise ValidationError("Transaction ID is required for non-cash payments.")
    return transaction_id


def _apply_line_payment(
    line_item,
    amount_paid,
    payment_method,
    user,
    transaction_id="",
    payer_phone="",
    network="",
    bank_name="",
    bank_account="",
    card_last_four="",
    cardholder_name="",
):
    if amount_paid <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    outstanding = line_item.amount - line_item.paid_amount
    if amount_paid > outstanding:
        raise ValidationError(f"Amount exceeds outstanding balance ({outstanding}).")

    drawer = _get_or_create_drawer(line_item.branch, line_item.service_type)

    InvoiceLinePayment.objects.create(
        branch=line_item.branch,
        line_item=line_item,
        drawer=drawer,
        amount_paid=amount_paid,
        payment_method=payment_method,
        transaction_id=transaction_id,
        payer_phone=payer_phone,
        network=network,
        bank_name=bank_name,
        bank_account=bank_account,
        card_last_four=card_last_four,
        cardholder_name=cardholder_name,
        received_by=user,
    )

    line_item.paid_amount = line_item.paid_amount + amount_paid
    if line_item.paid_amount >= line_item.amount:
        line_item.payment_status = "paid"
    elif line_item.paid_amount > 0:
        line_item.payment_status = "partial"
    else:
        line_item.payment_status = "pending"
    line_item.save(update_fields=["paid_amount", "payment_status", "updated_at"])


def _apply_invoice_payment(
    invoice,
    amount_paid,
    payment_method,
    user,
    transaction_id="",
    payer_phone="",
    network="",
    bank_name="",
    bank_account="",
    card_last_four="",
    cardholder_name="",
):
    if amount_paid <= 0:
        raise ValidationError("Payment amount must be greater than zero.")

    remaining_amount = amount_paid
    line_items = list(invoice.line_items.exclude(payment_status="paid").order_by("id"))

    payment_kwargs = dict(
        payer_phone=payer_phone,
        network=network,
        bank_name=bank_name,
        bank_account=bank_account,
        card_last_four=card_last_four,
        cardholder_name=cardholder_name,
    )

    for line_item in line_items:
        line_outstanding = line_item.amount - line_item.paid_amount
        if line_outstanding <= 0:
            continue

        applied_amount = min(line_outstanding, remaining_amount)
        _apply_line_payment(
            line_item,
            applied_amount,
            payment_method,
            user,
            transaction_id=transaction_id,
            **payment_kwargs,
        )
        remaining_amount -= applied_amount
        if remaining_amount <= 0:
            break

    # If line items could not absorb the full amount (totals mismatch
    # or no unpaid line items), bump the first line item so the
    # payment is recorded at the line-item level.
    if remaining_amount > 0:
        target = invoice.line_items.order_by("id").first()
        if target:
            target.refresh_from_db()
            target.amount = target.amount + remaining_amount
            target.save(update_fields=["amount", "updated_at"])
            _apply_line_payment(
                target,
                remaining_amount,
                payment_method,
                user,
                transaction_id=transaction_id,
                **payment_kwargs,
            )


def _find_open_invoice(branch, patient, visit=None):
    invoices = Invoice.objects.filter(
        branch=branch,
        patient=patient,
        payment_status__in=["pending", "partial", "post_payment"],
    )
    if visit:
        invoices = invoices.filter(visit=visit)
    return invoices.order_by("-created_at").first()


def _create_invoice_from_lines(
    request,
    *,
    patient,
    branch,
    visit=None,
    payment_method="cash",
    payment_status="pending",
):
    lines = _build_auto_invoice_lines(patient, branch, visit)
    if not lines:
        raise ValidationError(
            "No billable consultation, lab, radiology, referral, or pharmacy requests found for this patient."
        )

    total_amount = sum((line["amount"] for line in lines), Decimal("0.00"))
    invoice = Invoice.objects.create(
        branch=branch,
        invoice_number=_generate_invoice_number(branch),
        patient=patient,
        visit=visit,
        services="\n".join(
            f"{line['description']} - {line['amount']}" for line in lines
        ),
        total_amount=total_amount,
        payment_method=payment_method,
        payment_status=payment_status,
        cashier=request.user,
    )

    _log_financial_event(
        request,
        action="billing.invoice.create",
        object_type="invoice",
        object_id=invoice.pk,
        after={
            "invoice_number": invoice.invoice_number,
            "payment_status": invoice.payment_status,
            "payment_method": invoice.payment_method,
            "total_amount": str(invoice.total_amount),
        },
    )

    for line in lines:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            branch=invoice.branch,
            service_type=line["service_type"],
            description=line["description"],
            amount=line["amount"],
            paid_amount=Decimal("0.00"),
            payment_status="pending",
            unit_cost=line.get("unit_cost", Decimal("0.00")),
            total_cost=line.get("total_cost", Decimal("0.00")),
            profit_amount=line.get("profit_amount", line["amount"]),
            source_model=line["source_model"],
            source_id=line["source_id"],
        )
    return invoice


def _source_billed(source_model: str, source_id: int) -> bool:
    return InvoiceLineItem.objects.filter(
        source_model=source_model, source_id=source_id
    ).exists()


def _generate_invoice_number(branch):
    now = timezone.now()
    prefix = (branch.branch_name[0] if branch.branch_name else "X").upper()
    yy = now.strftime("%y")
    mm = now.strftime("%m")
    base = f"{prefix}{yy}{mm}"
    last = (
        Invoice.objects.filter(invoice_number__startswith=base)
        .order_by("-invoice_number")
        .values_list("invoice_number", flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{base}-{seq:02d}"


def _generate_receipt_number(branch):
    now = timezone.now()
    prefix = (branch.branch_name[0] if branch.branch_name else "X").upper()
    yy = now.strftime("%y")
    mm = now.strftime("%m")
    base = f"R{prefix}{yy}{mm}"
    last = (
        Receipt.objects.filter(receipt_number__startswith=base)
        .order_by("-receipt_number")
        .values_list("receipt_number", flat=True)
        .first()
    )
    seq = 1
    if last:
        try:
            seq = int(last.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{base}-{seq:02d}"


def _create_receipt(
    invoice,
    amount_paid,
    payment_method,
    received_by,
    receipt_type="full",
    notes="",
    transaction_id="",
    service_type="",
    service_description="",
):
    balance_due = invoice.total_amount - invoice.amount_paid
    return Receipt.objects.create(
        branch=invoice.branch,
        receipt_number=_generate_receipt_number(invoice.branch),
        invoice=invoice,
        patient=invoice.patient,
        amount_paid=amount_paid,
        total_invoice_amount=invoice.total_amount,
        balance_due=max(balance_due, Decimal("0.00")),
        payment_method=payment_method,
        transaction_id=transaction_id,
        receipt_type=receipt_type,
        received_by=received_by,
        notes=notes,
        service_type=service_type,
        service_description=service_description,
    )


def _build_receipt_service_info(invoice):
    """Determine service_type and a human-readable description from invoice line items."""
    line_items = invoice.line_items.all()
    if not line_items:
        return "", ""
    types = set(li.service_type for li in line_items)
    if len(types) == 1:
        stype = types.pop()
    else:
        stype = "mixed"
    type_labels = dict(InvoiceLineItem.SERVICE_TYPES)
    descriptions = []
    for li in line_items:
        label = type_labels.get(li.service_type, li.service_type)
        descriptions.append(f"{label}: {li.description}")
    return stype, "; ".join(descriptions)[:500]


def _service_code_for_line(line_item):
    if line_item.service_type == "consultation":
        return "consultation"

    if line_item.service_type == "lab":
        lab = (
            LabRequest.objects.filter(pk=line_item.source_id).only("test_type").first()
        )
        return lab.test_type if lab else ""

    if line_item.service_type == "radiology":
        imaging = (
            ImagingRequest.objects.filter(pk=line_item.source_id)
            .only("specific_examination", "imaging_type")
            .first()
        )
        if not imaging:
            return ""
        return imaging.specific_examination or imaging.imaging_type

    return ""


def _consume_stock_for_invoice(invoice, consumed_by=None):
    line_items = invoice.line_items.filter(
        stock_deducted_at__isnull=True,
        service_type__in=["consultation", "lab", "radiology"],
    )

    for line_item in line_items:
        if line_item.service_type in {"lab", "radiology"}:
            line_item.unit_cost = Decimal("0.00")
            line_item.total_cost = Decimal("0.00")
            line_item.profit_amount = Decimal("0.00")
            line_item.save(
                update_fields=[
                    "unit_cost",
                    "total_cost",
                    "profit_amount",
                    "updated_at",
                ]
            )

            if line_item.source_model == "lab":
                LabRequest.objects.filter(pk=line_item.source_id).update(
                    unit_cost_snapshot=Decimal("0.0000"),
                    total_cost_snapshot=Decimal("0.00"),
                    profit_amount=Decimal("0.00"),
                )
            elif line_item.source_model == "radiology":
                ImagingRequest.objects.filter(pk=line_item.source_id).update(
                    unit_cost_snapshot=Decimal("0.0000"),
                    total_cost_snapshot=Decimal("0.00"),
                    profit_amount=Decimal("0.00"),
                )
            continue

        service_code = _service_code_for_line(line_item)
        if not service_code:
            continue
        allocations = allocate_service_stock(
            invoice.branch,
            line_item.service_type,
            service_code,
            quantity=1,
            consumed_by=consumed_by,
            source_model=line_item.source_model,
            source_id=line_item.source_id,
            reference=f"Invoice {invoice.invoice_number} paid",
        )
        total_cost = sum(
            (allocation["total_cost"] for allocation in allocations),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        unit_cost = (
            (total_cost / Decimal(sum(a["quantity"] for a in allocations))).quantize(
                Decimal("0.0001")
            )
            if allocations
            else Decimal("0.0000")
        )
        line_item.unit_cost = unit_cost
        line_item.total_cost = total_cost
        line_item.profit_amount = line_item.amount - total_cost
        line_item.stock_deducted_at = timezone.now()
        line_item.save(
            update_fields=[
                "unit_cost",
                "total_cost",
                "profit_amount",
                "stock_deducted_at",
                "updated_at",
            ]
        )

        if line_item.source_model == "lab":
            LabRequest.objects.filter(pk=line_item.source_id).update(
                unit_cost_snapshot=unit_cost,
                total_cost_snapshot=total_cost,
                profit_amount=line_item.profit_amount,
            )
        elif line_item.source_model == "radiology":
            ImagingRequest.objects.filter(pk=line_item.source_id).update(
                unit_cost_snapshot=unit_cost,
                total_cost_snapshot=total_cost,
                profit_amount=line_item.profit_amount,
            )


def _visit_ready_for_triage_after_payment(visit):
    if not visit:
        return False
    if visit.triage_records.exists():
        return False
    if LabRequest.objects.filter(
        visit=visit,
        status__in=["requested", "processing", "completed", "reviewed"],
    ).exists():
        return False
    if ImagingRequest.objects.filter(
        visit=visit,
        status__in=[
            "requested",
            "scheduled",
            "patient_arrived",
            "scanning",
            "reporting",
            "completed",
        ],
    ).exists():
        return False
    if PharmacyRequest.objects.filter(
        visit=visit,
        status="requested",
    ).exists():
        return False
    return True


def _build_auto_invoice_lines(patient, branch, visit=None):
    lines = []
    guarded_pharmacy_pairs = set()

    consultations = Consultation.objects.filter(patient=patient, branch=branch)
    if visit:
        consultations = consultations.filter(visit=visit)
    consultations = consultations.order_by("created_at")
    for item in consultations:
        if not _source_billed("consultation", item.id):
            charge = get_consultation_fee()
            cost = service_stock_cost(branch, "consultation", "consultation")
            lines.append(
                {
                    "service_type": "consultation",
                    "description": f"Consultation - {item.created_at:%Y-%m-%d}",
                    "amount": charge,
                    "unit_cost": cost,
                    "total_cost": cost,
                    "profit_amount": charge - cost,
                    "source_model": "consultation",
                    "source_id": item.id,
                }
            )

    lab_requests = LabRequest.objects.filter(
        patient=patient,
        branch=branch,
        status__in=["requested", "processing", "completed", "reviewed"],
    )
    if visit:
        lab_requests = lab_requests.filter(visit=visit)
    lab_requests = lab_requests.order_by("date")
    for item in lab_requests:
        if not _source_billed("lab", item.id):
            charge = get_lab_fee(item.test_type)
            lines.append(
                {
                    "service_type": "lab",
                    "description": f"Lab Test - {item.test_type}",
                    "amount": charge,
                    "unit_cost": Decimal("0.00"),
                    "total_cost": Decimal("0.00"),
                    "profit_amount": Decimal("0.00"),
                    "source_model": "lab",
                    "source_id": item.id,
                }
            )

    imaging_requests = ImagingRequest.objects.filter(
        patient=patient,
        branch=branch,
        status__in=[
            "requested",
            "scheduled",
            "patient_arrived",
            "scanning",
            "reporting",
            "completed",
        ],
    )
    if visit:
        imaging_requests = imaging_requests.filter(visit=visit)
    imaging_requests = imaging_requests.order_by("date_requested")
    for item in imaging_requests:
        if not _source_billed("radiology", item.id):
            charge = get_radiology_fee(
                item.imaging_type,
                item.specific_examination,
            )
            lines.append(
                {
                    "service_type": "radiology",
                    "description": f"Radiology - {item.get_imaging_type_display()}",
                    "amount": charge,
                    "unit_cost": Decimal("0.00"),
                    "total_cost": Decimal("0.00"),
                    "profit_amount": Decimal("0.00"),
                    "source_model": "radiology",
                    "source_id": item.id,
                }
            )

    referrals = Referral.objects.filter(patient=patient, branch=branch)
    if visit:
        referrals = referrals.filter(visit=visit)
    referrals = referrals.order_by("referral_date")
    for item in referrals:
        if not _source_billed("referral", item.id):
            lines.append(
                {
                    "service_type": "referral",
                    "description": f"Referral - {item.facility_name}",
                    "amount": REFERRAL_FEE,
                    "unit_cost": Decimal("0.00"),
                    "total_cost": Decimal("0.00"),
                    "profit_amount": REFERRAL_FEE,
                    "source_model": "referral",
                    "source_id": item.id,
                }
            )

    sync_branch_medicine_catalog(branch)

    pharmacy_requests = PharmacyRequest.objects.filter(
        patient=patient,
        branch=branch,
        status="requested",
    )
    if visit:
        pharmacy_requests = pharmacy_requests.filter(visit=visit)
    pharmacy_requests = pharmacy_requests.select_related("medicine").order_by(
        "date_requested"
    )
    for item in pharmacy_requests:
        if not _source_billed("pharmacy_request", item.id):
            amount = item.unit_price_snapshot * Decimal(item.quantity)
            total_cost = item.medicine.current_purchase_price * Decimal(item.quantity)
            lines.append(
                {
                    "service_type": "pharmacy",
                    "description": f"Pharmacy Request - {item.medicine.name} x{item.quantity}",
                    "amount": amount,
                    "unit_cost": item.medicine.current_purchase_price,
                    "total_cost": total_cost,
                    "profit_amount": amount - total_cost,
                    "source_model": "pharmacy_request",
                    "source_id": item.id,
                }
            )
        if item.visit_id and item.patient_id and item.medicine_id:
            guarded_pharmacy_pairs.add(
                (item.visit_id, item.patient_id, item.medicine_id)
            )

    dispenses = DispenseRecord.objects.filter(patient=patient, branch=branch)
    if visit:
        dispenses = dispenses.filter(visit=visit)
    dispenses = dispenses.order_by("dispensed_at")
    for item in dispenses:
        # Guard against legacy double-billing when a doctor pharmacy request
        # already represents this same clinical intent.
        if item.visit_id and item.patient_id and item.medicine_id:
            pair = (item.visit_id, item.patient_id, item.medicine_id)
            if pair in guarded_pharmacy_pairs:
                continue
            if PharmacyRequest.objects.filter(
                branch=branch,
                visit_id=item.visit_id,
                patient_id=item.patient_id,
                medicine_id=item.medicine_id,
                status__in=["requested", "dispensed"],
            ).exists():
                continue
        if not _source_billed("pharmacy", item.id):
            amount = item.unit_price * Decimal(item.quantity)
            total_cost = item.total_cost_snapshot or (
                item.medicine.current_purchase_price * Decimal(item.quantity)
            )
            unit_cost = item.unit_cost_snapshot or item.medicine.current_purchase_price
            lines.append(
                {
                    "service_type": "pharmacy",
                    "description": f"Pharmacy - {item.medicine.name} x{item.quantity}",
                    "amount": amount,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "profit_amount": item.profit_amount or (amount - total_cost),
                    "source_model": "pharmacy",
                    "source_id": item.id,
                }
            )

    return lines


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def index(request):
    return_to = _safe_return_url(request)
    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "all").strip().lower()
    request_type = (request.GET.get("request_type") or "all").strip().lower()
    payment_method_filter = (request.GET.get("payment_method") or "all").strip().lower()

    queryset = branch_queryset_for_user(
        request.user,
        Invoice.objects.select_related("patient", "cashier").order_by("-created_at"),
    )
    if status in {"pending", "paid", "partial", "post_payment"}:
        queryset = queryset.filter(payment_status=status)
    else:
        status = "all"

    if payment_method_filter in {choice for choice, _ in Invoice.PAYMENT_METHODS}:
        queryset = queryset.filter(payment_method=payment_method_filter)
    else:
        payment_method_filter = "all"

    if query:
        queryset = queryset.filter(
            Q(invoice_number__icontains=query)
            | Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(visit__visit_number__icontains=query)
            | Q(services__icontains=query)
        )

    billed_lab_ids = set(
        branch_queryset_for_user(
            request.user,
            InvoiceLineItem.objects.filter(source_model="lab"),
        ).values_list("source_id", flat=True)
    )
    billed_radiology_ids = set(
        branch_queryset_for_user(
            request.user,
            InvoiceLineItem.objects.filter(source_model="radiology"),
        ).values_list("source_id", flat=True)
    )
    billed_referral_ids = set(
        branch_queryset_for_user(
            request.user,
            InvoiceLineItem.objects.filter(source_model="referral"),
        ).values_list("source_id", flat=True)
    )
    billed_pharmacy_request_ids = set(
        branch_queryset_for_user(
            request.user,
            InvoiceLineItem.objects.filter(source_model="pharmacy_request"),
        ).values_list("source_id", flat=True)
    )

    pending_requests = []

    pending_labs = branch_queryset_for_user(
        request.user,
        LabRequest.objects.select_related("patient", "visit", "requested_by")
        .filter(status="requested")
        .exclude(pk__in=billed_lab_ids)
        .order_by("-date"),
    )
    for req in pending_labs:
        pending_requests.append(
            {
                "request_type": "lab",
                "request_type_label": "Lab",
                "patient_name": f"{req.patient.first_name} {req.patient.last_name}",
                "patient_id": req.patient_id,
                "visit_number": req.visit.visit_number if req.visit else "-",
                "visit_id": req.visit_id,
                "description": req.test_type,
                "requested_by": req.requested_by.get_full_name()
                or req.requested_by.username,
                "requested_on": req.date,
            }
        )

    pending_radiology = branch_queryset_for_user(
        request.user,
        ImagingRequest.objects.select_related("patient", "visit", "requested_by")
        .filter(status="requested")
        .exclude(pk__in=billed_radiology_ids)
        .order_by("-date_requested"),
    )
    for req in pending_radiology:
        pending_requests.append(
            {
                "request_type": "radiology",
                "request_type_label": "Radiology",
                "patient_name": f"{req.patient.first_name} {req.patient.last_name}",
                "patient_id": req.patient_id,
                "visit_number": req.visit.visit_number if req.visit else "-",
                "visit_id": req.visit_id,
                "description": req.get_imaging_type_display(),
                "requested_by": req.requested_by.get_full_name()
                or req.requested_by.username,
                "requested_on": req.date_requested,
            }
        )

    pending_referrals = branch_queryset_for_user(
        request.user,
        Referral.objects.select_related("patient", "visit", "referring_doctor")
        .exclude(pk__in=billed_referral_ids)
        .order_by("-referral_date"),
    )
    for req in pending_referrals:
        pending_requests.append(
            {
                "request_type": "referral",
                "request_type_label": "Referral",
                "patient_name": f"{req.patient.first_name} {req.patient.last_name}",
                "patient_id": req.patient_id,
                "visit_number": req.visit.visit_number if req.visit else "-",
                "visit_id": req.visit_id,
                "description": req.facility_name,
                "requested_by": req.referring_doctor.get_full_name()
                or req.referring_doctor.username,
                "requested_on": req.referral_date,
            }
        )

    pending_pharmacy_requests = branch_queryset_for_user(
        request.user,
        PharmacyRequest.objects.select_related(
            "patient", "visit", "requested_by", "medicine"
        )
        .filter(status="requested")
        .exclude(pk__in=billed_pharmacy_request_ids)
        .order_by("-date_requested"),
    )
    for req in pending_pharmacy_requests:
        pending_requests.append(
            {
                "request_type": "pharmacy",
                "request_type_label": "Pharmacy",
                "patient_name": f"{req.patient.first_name} {req.patient.last_name}",
                "patient_id": req.patient_id,
                "visit_number": req.visit.visit_number if req.visit else "-",
                "visit_id": req.visit_id,
                "description": f"{req.medicine.name} x{req.quantity}",
                "requested_by": req.requested_by.get_full_name()
                or req.requested_by.username,
                "requested_on": req.date_requested,
            }
        )

    pending_request_counts = {
        "lab": pending_labs.count(),
        "radiology": pending_radiology.count(),
        "referral": pending_referrals.count(),
        "pharmacy": pending_pharmacy_requests.count(),
    }
    pending_request_counts["all"] = sum(pending_request_counts.values())

    if request_type not in {"all", "lab", "radiology", "referral", "pharmacy"}:
        request_type = "all"
    if request_type != "all":
        pending_requests = [
            item for item in pending_requests if item["request_type"] == request_type
        ]

    if query:
        query_lower = query.lower()
        pending_requests = [
            item
            for item in pending_requests
            if query_lower in item["patient_name"].lower()
            or query_lower in item["visit_number"].lower()
            or query_lower in item["description"].lower()
            or query_lower in item["requested_by"].lower()
        ]

    pending_requests = sorted(
        pending_requests,
        key=lambda item: item["requested_on"],
        reverse=True,
    )

    # Visits in billing_queue with pending invoices awaiting cashier payment
    visits_awaiting_payment = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient", "created_by")
        .filter(status="billing_queue")
        .order_by("-check_in_time"),
    )
    visit_pending_invoices = []
    for visit in visits_awaiting_payment:
        invoice = (
            Invoice.objects.filter(
                visit=visit,
                payment_status="pending",
                branch=visit.branch,
            )
            .order_by("-created_at")
            .first()
        )
        visit_pending_invoices.append(
            {
                "visit": visit,
                "invoice": invoice,
            }
        )

    paginator = Paginator(queryset, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    active_shift = None
    if request.user.role in {"cashier", "receptionist"}:
        active_shift = _get_open_shift_for_user(request.user)

    return render(
        request,
        "billing/index.html",
        {
            "invoices": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "selected_status": status,
            "selected_request_type": request_type,
            "selected_payment_method": payment_method_filter,
            "pending_request_counts": pending_request_counts,
            "pending_requests": pending_requests,
            "visit_pending_invoices": visit_pending_invoices,
            "active_shift": active_shift,
            "return_to": return_to,
        },
    )


def _get_invoice_for_user_or_404(user, pk):
    invoice = (
        Invoice.objects.select_related("patient", "cashier", "branch")
        .filter(pk=pk)
        .first()
    )
    if not invoice:
        raise Http404("Invoice not found")
    scoped = branch_queryset_for_user(user, Invoice.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Invoice not found")
    return invoice


@login_required
@role_required("cashier", "system_admin", "director")
@module_permission_required("billing", "create")
def create(request):
    return_to = _safe_return_url(request)
    initial = {}
    patient_id = (request.GET.get("patient") or "").strip()
    visit_id = (request.GET.get("visit") or "").strip()
    fixed_patient = None
    fixed_visit = None

    try:
        if visit_id:
            fixed_visit = branch_queryset_for_user(
                request.user,
                Visit.objects.select_related("patient").filter(pk=int(visit_id)),
            ).first()
            if fixed_visit:
                initial["visit"] = fixed_visit.pk
                initial["patient"] = fixed_visit.patient_id
        if patient_id and "patient" not in initial:
            fixed_patient = branch_queryset_for_user(
                request.user,
                Patient.objects.filter(pk=int(patient_id)),
            ).first()
            if fixed_patient:
                initial["patient"] = fixed_patient.pk
    except (TypeError, ValueError):
        initial = {}

    if fixed_visit and not fixed_patient:
        fixed_patient = fixed_visit.patient

    if request.method == "GET" and request.GET.get("autocreate") == "1":
        if not request.user.branch_id:
            messages.error(request, "Your user account has no branch assigned.")
            return _redirect_with_return_to(reverse("billing:index"), return_to)
        if fixed_patient:
            existing_invoice = _find_open_invoice(
                request.user.branch,
                fixed_patient,
                fixed_visit,
            )
            if existing_invoice:
                return _redirect_with_return_to(
                    reverse("billing:detail", args=[existing_invoice.pk]),
                    return_to,
                )
            try:
                invoice = _create_invoice_from_lines(
                    request,
                    patient=fixed_patient,
                    branch=request.user.branch,
                    visit=fixed_visit,
                )
            except ValidationError as exc:
                messages.error(request, str(exc))
                return _redirect_with_return_to(reverse("billing:index"), return_to)
            return _redirect_with_return_to(
                reverse("billing:detail", args=[invoice.pk]),
                return_to,
            )

    if request.method == "POST":
        form = InvoiceForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                invoice = form.save(commit=False)
                if invoice.visit and not invoice.patient_id:
                    invoice.patient = invoice.visit.patient
                try:
                    invoice = _create_invoice_from_lines(
                        request,
                        patient=invoice.patient,
                        branch=request.user.branch,
                        visit=invoice.visit,
                        payment_method=invoice.payment_method,
                        payment_status=invoice.payment_status,
                    )
                except ValidationError as exc:
                    form.add_error(None, str(exc))
                    return render(
                        request,
                        "billing/form.html",
                        {
                            "form": form,
                            "page_title": "Create Invoice",
                            "submit_label": "Create Invoice",
                        },
                    )

                return _redirect_with_return_to(
                    reverse("billing:detail", args=[invoice.pk]),
                    return_to,
                )
    else:
        form = InvoiceForm(user=request.user, initial=initial)

    return render(
        request,
        "billing/form.html",
        {
            "form": form,
            "page_title": "Create Invoice",
            "submit_label": "Create Invoice",
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def detail(request, pk):
    return_to = _safe_return_url(request)
    invoice = _get_invoice_for_user_or_404(request.user, pk)
    line_items = invoice.line_items.order_by("id")
    payment_form = InvoicePaymentForm(
        initial={
            "payment_status": "paid",
            "payment_method": invoice.payment_method or "cash",
            "amount_paid": invoice.balance_due_amount,
        }
    )
    line_payments = (
        InvoiceLinePayment.objects.select_related("received_by", "line_item")
        .filter(line_item__invoice=invoice)
        .order_by("-paid_at")
    )
    payment_page_obj = Paginator(line_payments, 3).get_page(
        request.GET.get("payment_page")
    )
    receipt_page_obj = Paginator(invoice.receipts.order_by("-created_at"), 3).get_page(
        request.GET.get("receipt_page")
    )
    return render(
        request,
        "billing/detail.html",
        {
            "invoice": invoice,
            "line_items": line_items,
            "line_payments": payment_page_obj.object_list,
            "payment_page_obj": payment_page_obj,
            "receipt_history": receipt_page_obj.object_list,
            "receipt_page_obj": receipt_page_obj,
            "payment_form": payment_form,
            "delete_object_type": "Invoice",
            "delete_object_id": invoice.pk,
            "delete_object_label": invoice.invoice_number,
            "delete_next_url": request.path,
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "update")
def update_payment_status(request, pk):
    return_to = _safe_return_url(request)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if request.method != "POST":
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    def _error_response(msg):
        if is_ajax:
            return JsonResponse({"ok": False, "error": msg}, status=400)
        messages.error(request, msg)
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    invoice = _get_invoice_for_user_or_404(request.user, pk)
    previous_status = invoice.payment_status
    new_status = request.POST.get("payment_status", "").strip().lower()
    reason = (request.POST.get("status_reason") or "").strip()
    allowed_statuses = {"pending", "paid", "partial", "post_payment"}
    if new_status not in allowed_statuses:
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    if previous_status == "paid" and new_status in {"pending", "partial"}:
        if not reason:
            return _error_response(
                "Reason is required when requesting a paid invoice rollback."
            )

        approval_request, created = _create_paid_rollback_request(
            request,
            invoice=invoice,
            new_status=new_status,
            payment_method=request.POST.get("payment_method", "").strip().lower(),
            reason=reason,
        )
        if created:
            _log_financial_event(
                request,
                action="billing.approval_request.create",
                object_type="approval_request",
                object_id=approval_request.pk,
                after={
                    "approval_type": approval_request.approval_type,
                    "invoice": invoice.invoice_number,
                    "from_status": approval_request.from_status,
                    "to_status": approval_request.to_status,
                },
                reason=reason,
            )
            messages.info(
                request,
                "Rollback request submitted for approval. Invoice status remains paid until approval.",
            )
        else:
            messages.info(
                request,
                "A pending rollback approval request already exists for this invoice.",
            )
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    payment_method = request.POST.get("payment_method", "").strip().lower()
    valid_methods = {choice for choice, _ in Invoice.PAYMENT_METHODS}
    transaction_id = (request.POST.get("transaction_id") or "").strip()
    payment_notes = (request.POST.get("notes") or "").strip()
    payment_form = InvoicePaymentForm(request.POST)
    if new_status in {"paid", "partial"} and not payment_form.is_valid():
        errs = [e for el in payment_form.errors.values() for e in el]
        if is_ajax:
            return JsonResponse({"ok": False, "error": "; ".join(errs)}, status=400)
        for error in errs:
            messages.error(request, error)
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    if request.user.role in {"cashier", "receptionist"} and new_status in {
        "paid",
        "partial",
    }:
        shift = _get_open_shift_for_user(request.user)
        if not shift:
            return _error_response(
                "Open a cashier shift and capture opening float before posting a payment."
            )

    rcpt = None
    amount_to_apply = Decimal("0.00")
    try:
        with transaction.atomic():
            previous_method = invoice.payment_method
            update_fields = ["payment_status", "cashier", "updated_at"]
            invoice.cashier = request.user

            if payment_method in valid_methods:
                invoice.payment_method = payment_method
                update_fields.append("payment_method")

            if new_status == "post_payment":
                invoice.payment_status = "post_payment"
                invoice.save(update_fields=update_fields)
            else:
                _require_transaction_id(invoice.payment_method, transaction_id)

                if new_status == "paid":
                    amount_to_apply = invoice.balance_due_amount
                    if amount_to_apply <= 0:
                        raise ValidationError("This invoice is already fully paid.")
                else:
                    amount_to_apply = payment_form.cleaned_data["amount_paid"]
                    if amount_to_apply >= invoice.balance_due_amount:
                        raise ValidationError(
                            "Partial payment must be less than the current outstanding balance. Use Full Payment instead."
                        )

                _apply_invoice_payment(
                    invoice,
                    amount_to_apply,
                    invoice.payment_method,
                    request.user,
                    transaction_id=transaction_id,
                    payer_phone=payment_form.cleaned_data.get("payer_phone", ""),
                    network=payment_form.cleaned_data.get("network", ""),
                    bank_name=payment_form.cleaned_data.get("bank_name", ""),
                    bank_account=payment_form.cleaned_data.get("bank_account", ""),
                    card_last_four=payment_form.cleaned_data.get("card_last_four", ""),
                    cardholder_name=payment_form.cleaned_data.get(
                        "cardholder_name", ""
                    ),
                )

                invoice.amount_paid = invoice.amount_paid + amount_to_apply
                if "amount_paid" not in update_fields:
                    update_fields.append("amount_paid")

                svc_type, svc_desc = _build_receipt_service_info(invoice)

                if new_status == "paid":
                    invoice.payment_status = "paid"
                    invoice.save(update_fields=update_fields)
                    if previous_status != "paid":
                        _consume_stock_for_invoice(invoice, consumed_by=request.user)
                    rcpt = _create_receipt(
                        invoice,
                        amount_to_apply,
                        invoice.payment_method,
                        request.user,
                        receipt_type="full",
                        notes=payment_notes,
                        transaction_id=transaction_id,
                        service_type=svc_type,
                        service_description=svc_desc,
                    )
                else:
                    invoice.payment_status = "partial"
                    invoice.save(update_fields=update_fields)
                    rcpt = _create_receipt(
                        invoice,
                        amount_to_apply,
                        invoice.payment_method,
                        request.user,
                        receipt_type="partial",
                        notes=payment_notes,
                        transaction_id=transaction_id,
                        service_type=svc_type,
                        service_description=svc_desc,
                    )

            _log_financial_event(
                request,
                action="billing.invoice.status_change",
                object_type="invoice",
                object_id=invoice.pk,
                before={
                    "payment_status": previous_status,
                    "payment_method": previous_method,
                },
                after={
                    "payment_status": invoice.payment_status,
                    "payment_method": invoice.payment_method,
                    "amount_paid": str(amount_to_apply),
                    "transaction_id": transaction_id,
                },
                reason=payment_notes or reason,
            )
    except ValidationError as exc:
        return _error_response(str(exc))

    if invoice.visit:
        if new_status in ("paid", "post_payment"):
            pending_lab_request = LabRequest.objects.filter(
                visit=invoice.visit,
                status="requested",
            ).exists()
            pending_radiology_request = ImagingRequest.objects.filter(
                visit=invoice.visit,
                status__in=[
                    "requested",
                    "scheduled",
                    "patient_arrived",
                    "scanning",
                    "reporting",
                ],
            ).exists()
            pending_pharmacy = DispenseRecord.objects.filter(
                visit=invoice.visit,
            ).exists()
            pending_pharmacy_request = PharmacyRequest.objects.filter(
                visit=invoice.visit,
                status="requested",
            ).exists()
            pending_referral = Referral.objects.filter(
                visit=invoice.visit,
            ).exists()
            if _visit_ready_for_triage_after_payment(invoice.visit):
                transition_visit(invoice.visit, "waiting_triage", request.user)
            elif pending_lab_request:
                transition_visit(invoice.visit, "lab_requested", request.user)
            elif pending_radiology_request:
                transition_visit(invoice.visit, "radiology_requested", request.user)
            elif pending_pharmacy_request or pending_pharmacy:
                transition_visit(invoice.visit, "waiting_pharmacy", request.user)
            else:
                transition_visit(invoice.visit, "waiting_doctor", request.user)
        elif invoice.visit.status != "billing_queue":
            transition_visit(invoice.visit, "billing_queue", request.user)

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if is_ajax:
        receipt_html = ""
        if rcpt:
            receipt_html = render_to_string(
                "billing/receipt_detail.html",
                {
                    "receipt": rcpt,
                    "invoice": invoice,
                    "line_items": invoice.line_items.all(),
                },
                request=request,
            )
        msg = ""
        if invoice.payment_status == "partial":
            msg = "Partial payment recorded. The invoice balance has been updated."
        elif invoice.payment_status == "post_payment":
            msg = "Invoice marked as Post Payment. Patient may proceed; payment is deferred."
        elif invoice.payment_status == "paid":
            msg = "Payment recorded successfully."
        return JsonResponse(
            {
                "ok": True,
                "receipt_html": receipt_html,
                "status": invoice.payment_status,
                "message": msg,
            }
        )

    if invoice.payment_status == "paid" and rcpt:
        return _redirect_with_return_to(
            reverse("billing:receipt_detail", args=[rcpt.pk]), return_to
        )
    elif invoice.payment_status == "paid":
        return _redirect_with_return_to(
            reverse("billing:receipt", args=[pk]), return_to
        )
    elif invoice.payment_status == "partial" and rcpt:
        messages.success(
            request,
            "Partial payment recorded. The invoice balance has been updated.",
        )
        return _redirect_with_return_to(
            reverse("billing:receipt_detail", args=[rcpt.pk]), return_to
        )
    elif invoice.payment_status == "post_payment":
        messages.success(
            request,
            "Invoice marked as Post Payment. Patient may proceed; payment is deferred.",
        )
    return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "update")
def pay_line_item(request, pk, line_id):
    return_to = _safe_return_url(request)
    if request.method != "POST":
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    invoice = _get_invoice_for_user_or_404(request.user, pk)
    line_item = invoice.line_items.filter(pk=line_id).first()
    if not line_item:
        raise Http404("Invoice line item not found")

    form = LineItemPaymentForm(
        request.POST,
        user=request.user,
        service_type=line_item.service_type,
    )
    if not form.is_valid():
        messages.error(request, "Invalid line payment details.")
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    if request.user.role in {"cashier", "receptionist"}:
        shift = _get_open_shift_for_user(request.user)
        if not shift:
            messages.error(
                request,
                "Open a cashier shift and capture opening float before posting line payments.",
            )
            return _redirect_with_return_to(
                reverse("billing:detail", args=[pk]), return_to
            )

    rcpt = None
    rcpt_type = None
    try:
        with transaction.atomic():
            previous_line_paid_amount = line_item.paid_amount
            previous_line_status = line_item.payment_status
            _apply_line_payment(
                line_item,
                form.cleaned_data["amount_paid"],
                form.cleaned_data["payment_method"],
                request.user,
                transaction_id=form.cleaned_data.get("transaction_id", ""),
                payer_phone=form.cleaned_data.get("payer_phone", ""),
                network=form.cleaned_data.get("network", ""),
                bank_name=form.cleaned_data.get("bank_name", ""),
                bank_account=form.cleaned_data.get("bank_account", ""),
                card_last_four=form.cleaned_data.get("card_last_four", ""),
                cardholder_name=form.cleaned_data.get("cardholder_name", ""),
            )

            invoice.amount_paid = invoice.amount_paid + form.cleaned_data["amount_paid"]

            amounts = invoice.line_items.aggregate(
                billed_total=Sum("amount"),
                paid_total=Sum("paid_amount"),
            )
            billed_total = amounts.get("billed_total") or Decimal("0.00")
            paid_total = amounts.get("paid_total") or Decimal("0.00")

            if paid_total >= billed_total and billed_total > 0:
                invoice.payment_status = "paid"
                invoice.payment_method = form.cleaned_data["payment_method"]
                invoice.save(
                    update_fields=[
                        "payment_status",
                        "payment_method",
                        "amount_paid",
                        "updated_at",
                    ]
                )
                _consume_stock_for_invoice(invoice, consumed_by=request.user)
                rcpt_type = "full"
            elif paid_total > 0:
                invoice.payment_status = "partial"
                invoice.payment_method = form.cleaned_data["payment_method"]
                invoice.save(
                    update_fields=[
                        "payment_status",
                        "payment_method",
                        "amount_paid",
                        "updated_at",
                    ]
                )
                rcpt_type = "partial"
            else:
                rcpt_type = None

            if rcpt_type:
                li_svc_type, li_svc_desc = _build_receipt_service_info(invoice)
                rcpt = _create_receipt(
                    invoice,
                    form.cleaned_data["amount_paid"],
                    form.cleaned_data["payment_method"],
                    request.user,
                    receipt_type=rcpt_type,
                    transaction_id=form.cleaned_data.get("transaction_id", ""),
                    service_type=li_svc_type,
                    service_description=li_svc_desc,
                )

            _log_financial_event(
                request,
                action="billing.line_payment.create",
                object_type="invoice_line_item",
                object_id=line_item.pk,
                before={
                    "paid_amount": str(previous_line_paid_amount),
                    "payment_status": previous_line_status,
                },
                after={
                    "paid_amount": str(line_item.paid_amount),
                    "payment_status": line_item.payment_status,
                    "amount_paid": str(form.cleaned_data["amount_paid"]),
                    "payment_method": form.cleaned_data["payment_method"],
                    "transaction_id": form.cleaned_data.get("transaction_id", ""),
                },
            )
    except ValidationError as exc:
        messages.error(request, str(exc))
        return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)

    messages.success(request, "Payment posted successfully. Receipt generated.")
    if rcpt_type:
        return _redirect_with_return_to(
            reverse("billing:receipt_detail", args=[rcpt.pk]), return_to
        )
    return _redirect_with_return_to(reverse("billing:detail", args=[pk]), return_to)


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def payments_register(request):
    return_to = _safe_return_url(request)
    cashier_filter = (request.GET.get("cashier") or "").strip()

    payments = branch_queryset_for_user(
        request.user,
        InvoiceLinePayment.objects.select_related(
            "line_item", "line_item__invoice", "received_by"
        ).order_by("-paid_at"),
    )

    if cashier_filter:
        payments = payments.filter(received_by_id=cashier_filter)

    query = request.GET.get("q", "").strip()
    if query:
        payments = payments.filter(
            Q(line_item__invoice__invoice_number__icontains=query)
            | Q(line_item__invoice__patient__first_name__icontains=query)
            | Q(line_item__invoice__patient__last_name__icontains=query)
        )

    page_obj = Paginator(payments, 25).get_page(request.GET.get("page"))
    cashiers = branch_queryset_for_user(
        request.user,
        request.user.__class__.objects.filter(role__in=["cashier", "receptionist"]),
    ).order_by("username")

    return render(
        request,
        "billing/payments_register.html",
        {
            "payments": page_obj.object_list,
            "page_obj": page_obj,
            "cashier_filter": cashier_filter,
            "cashiers": cashiers,
            "return_to": return_to,
            "query": query,
        },
    )


@login_required
@role_required("director", "system_admin")
@module_permission_required("billing", "view")
def approval_requests(request):
    status_filter = (request.GET.get("status") or "pending").strip().lower()
    queryset = branch_queryset_for_user(
        request.user,
        ApprovalRequest.objects.select_related(
            "invoice", "cashier_shift", "requested_by", "reviewed_by"
        ).order_by("-created_at"),
    )
    if status_filter in {"pending", "approved", "rejected", "cancelled"}:
        queryset = queryset.filter(status=status_filter)
    else:
        status_filter = "all"

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(invoice__invoice_number__icontains=query)
            | Q(requested_by__username__icontains=query)
            | Q(reason__icontains=query)
        )

    page_obj = Paginator(queryset, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "billing/approval_requests.html",
        {
            "approval_requests": page_obj.object_list,
            "page_obj": page_obj,
            "status_filter": status_filter,
            "query": query,
        },
    )


@login_required
@role_required("director", "system_admin")
@module_permission_required("billing", "update")
def review_approval_request(request, request_id):
    approval_request = get_object_or_404(ApprovalRequest, pk=request_id)
    scoped = branch_queryset_for_user(
        request.user, ApprovalRequest.objects.filter(pk=request_id)
    )
    if not scoped.exists():
        raise Http404("Approval request not found")

    if request.method != "POST":
        return render(
            request,
            "billing/review_approval_request.html",
            {"approval_request": approval_request},
        )

    if approval_request.status != "pending":
        messages.info(request, "This approval request is already resolved.")
        return redirect("billing:approval_requests")

    action = (request.POST.get("action") or "").strip().lower()
    reviewer_notes = (request.POST.get("reviewer_notes") or "").strip()

    if action not in {"approve", "reject"}:
        messages.error(request, "Invalid approval action.")
        return redirect("billing:approval_requests")

    invoice = approval_request.invoice
    shift = approval_request.cashier_shift
    if action == "approve":
        with transaction.atomic():
            if approval_request.approval_type == "paid_rollback" and invoice:
                previous_status = invoice.payment_status
                previous_method = invoice.payment_method

                invoice.payment_status = (
                    approval_request.to_status or invoice.payment_status
                )
                if approval_request.requested_payment_method:
                    invoice.payment_method = approval_request.requested_payment_method
                invoice.cashier = approval_request.requested_by
                invoice.save(
                    update_fields=[
                        "payment_status",
                        "payment_method",
                        "cashier",
                        "updated_at",
                    ]
                )

                if (
                    invoice.visit
                    and invoice.payment_status != "paid"
                    and invoice.visit.status != "billing_queue"
                ):
                    transition_visit(invoice.visit, "billing_queue", request.user)

                _log_financial_event(
                    request,
                    action="billing.approval_request.approved",
                    object_type="approval_request",
                    object_id=approval_request.pk,
                    before={
                        "invoice_status": previous_status,
                        "payment_method": previous_method,
                    },
                    after={
                        "invoice_status": invoice.payment_status,
                        "payment_method": invoice.payment_method,
                    },
                    reason=approval_request.reason,
                )

            if approval_request.approval_type == "shift_variance" and shift:
                shift.status = "closed"
                if not shift.closed_at:
                    shift.closed_at = timezone.now()
                shift.closed_by = request.user
                shift.save(
                    update_fields=[
                        "status",
                        "closed_at",
                        "closed_by",
                        "updated_at",
                    ]
                )

                _log_financial_event(
                    request,
                    action="billing.shift.approval.approved",
                    object_type="cashier_shift",
                    object_id=shift.pk,
                    before={"status": "pending_approval"},
                    after={"status": shift.status},
                    reason=approval_request.reason,
                )

            if approval_request.approval_type == "partial_payment" and invoice:
                _log_financial_event(
                    request,
                    action="billing.approval_request.approved",
                    object_type="approval_request",
                    object_id=approval_request.pk,
                    after={
                        "approval_type": "partial_payment",
                        "invoice": invoice.invoice_number,
                    },
                    reason=approval_request.reason,
                )

            approval_request.status = "approved"
            approval_request.reviewer_notes = reviewer_notes
            approval_request.reviewed_by = request.user
            approval_request.reviewed_at = timezone.now()
            approval_request.save(
                update_fields=[
                    "status",
                    "reviewer_notes",
                    "reviewed_by",
                    "reviewed_at",
                    "updated_at",
                ]
            )
        messages.success(request, "Approval request approved.")
    else:
        if approval_request.approval_type == "shift_variance" and shift:
            shift.status = "open"
            shift.closed_at = None
            shift.closed_by = None
            shift.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])

        approval_request.status = "rejected"
        approval_request.reviewer_notes = reviewer_notes
        approval_request.reviewed_by = request.user
        approval_request.reviewed_at = timezone.now()
        approval_request.save(
            update_fields=[
                "status",
                "reviewer_notes",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            ]
        )
        _log_financial_event(
            request,
            action="billing.approval_request.rejected",
            object_type="approval_request",
            object_id=approval_request.pk,
            reason=approval_request.reason,
        )
        messages.info(request, "Approval request rejected.")

    return redirect("billing:approval_requests")


@login_required
@role_required("director", "system_admin")
@module_permission_required("billing", "view")
def sequence_anomalies(request):
    anomalies = branch_queryset_for_user(
        request.user,
        FinancialSequenceAnomaly.objects.order_by("-anomaly_date", "-created_at"),
    )
    status_filter = (request.GET.get("status") or "open").strip().lower()
    if status_filter == "open":
        anomalies = anomalies.filter(is_resolved=False)
    elif status_filter == "resolved":
        anomalies = anomalies.filter(is_resolved=True)
    else:
        status_filter = "all"

    query = request.GET.get("q", "").strip()
    if query:
        anomalies = anomalies.filter(
            Q(anomaly_type__icontains=query) | Q(description__icontains=query)
        )

    page_obj = Paginator(anomalies, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "billing/sequence_anomalies.html",
        {
            "anomalies": page_obj.object_list,
            "page_obj": page_obj,
            "status_filter": status_filter,
            "query": query,
        },
    )


@login_required
@role_required("director", "system_admin")
@module_permission_required("billing", "view")
def shift_sessions_report(request):
    branch_filter = (request.GET.get("branch") or "").strip()
    status_filter = (request.GET.get("status") or "all").strip().lower()
    start_date_raw = (request.GET.get("start_date") or "").strip()
    end_date_raw = (request.GET.get("end_date") or "").strip()
    export_format = (request.GET.get("export") or "").strip().lower()

    start_date = parse_date(start_date_raw) if start_date_raw else None
    end_date = parse_date(end_date_raw) if end_date_raw else None

    sessions = branch_queryset_for_user(
        request.user,
        CashierShiftSession.objects.select_related(
            "branch", "opened_by", "closed_by"
        ).order_by("-created_at"),
    )

    if branch_filter:
        sessions = sessions.filter(branch_id=branch_filter)

    if status_filter in {"open", "pending_approval", "closed"}:
        sessions = sessions.filter(status=status_filter)
    else:
        status_filter = "all"

    if start_date:
        sessions = sessions.filter(created_at__date__gte=start_date)
    if end_date:
        sessions = sessions.filter(created_at__date__lte=end_date)

    branches = branch_queryset_for_user(
        request.user,
        Branch.objects.order_by("branch_name"),
    )

    if export_format == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="shift_sessions_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Shift ID",
                "Branch",
                "Opened By",
                "Opened At",
                "Closed By",
                "Closed At",
                "Status",
                "Opening Float",
                "Expected Cash",
                "Declared Cash",
                "Variance",
                "Variance Threshold",
            ]
        )
        for session in sessions:
            writer.writerow(
                [
                    session.pk,
                    session.branch.branch_name,
                    session.opened_by.get_full_name() or session.opened_by.username,
                    timezone.localtime(session.created_at).strftime("%Y-%m-%d %H:%M"),
                    (
                        session.closed_by.get_full_name() or session.closed_by.username
                        if session.closed_by
                        else ""
                    ),
                    (
                        timezone.localtime(session.closed_at).strftime("%Y-%m-%d %H:%M")
                        if session.closed_at
                        else ""
                    ),
                    session.get_status_display(),
                    session.opening_float,
                    session.expected_cash_total,
                    session.declared_cash_total or "",
                    session.variance_amount,
                    session.variance_threshold,
                ]
            )
        return response

    page_obj = Paginator(sessions, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "billing/shift_sessions_report.html",
        {
            "sessions": page_obj.object_list,
            "page_obj": page_obj,
            "branches": branches,
            "branch_filter": branch_filter,
            "status_filter": status_filter,
            "start_date": start_date_raw,
            "end_date": end_date_raw,
        },
    )


@login_required
@role_required("cashier", "receptionist", "director", "system_admin")
@module_permission_required("billing", "update")
def open_shift(request):
    if request.method == "POST":
        opening_float = request.POST.get("opening_float")
        if not opening_float or float(opening_float) <= 0:
            return render(
                request,
                "billing/open_shift.html",
                {"error": "Opening float must be a positive number."},
            )

        # Ensure no open shifts exist for the cashier
        if CashierShiftSession.objects.filter(
            opened_by=request.user, status="open"
        ).exists():
            return render(
                request,
                "billing/open_shift.html",
                {"error": "You already have an open shift."},
            )

        # Create a new shift
        CashierShiftSession.objects.create(
            branch=request.user.branch,
            opened_by=request.user,
            opening_float=opening_float,
            status="open",
        )
        return redirect("billing:index")

    return render(request, "billing/open_shift.html")


@login_required
@role_required("cashier", "receptionist", "director", "system_admin")
@module_permission_required("billing", "update")
def close_shift(request, shift_id):
    if request.method != "POST":
        return redirect("billing:index")

    shift = get_object_or_404(CashierShiftSession, pk=shift_id)
    scoped = branch_queryset_for_user(
        request.user, CashierShiftSession.objects.filter(pk=shift_id)
    )
    if not scoped.exists():
        raise Http404("Shift not found")

    if shift.status != "open":
        messages.info(request, "Only open shifts can be closed.")
        return redirect("billing:index")

    if (
        request.user.role not in {"director", "system_admin"}
        and shift.opened_by_id != request.user.id
    ):
        messages.error(request, "You can only close your own active shift.")
        return redirect("billing:index")

    declared_raw = (request.POST.get("declared_cash_total") or "").strip()
    reason = (request.POST.get("variance_reason") or "").strip()
    try:
        declared_cash_total = Decimal(declared_raw)
    except Exception:
        messages.error(request, "Enter a valid declared cash total.")
        return redirect("billing:index")

    if declared_cash_total < 0:
        messages.error(request, "Declared cash total cannot be negative.")
        return redirect("billing:index")

    closed_at = timezone.now()
    shift.closed_at = closed_at
    shift.closed_by = request.user
    shift.declared_cash_total = declared_cash_total
    shift.expected_cash_total = _expected_cash_for_shift(shift)
    shift.variance_amount = shift.declared_cash_total - shift.expected_cash_total

    if abs(shift.variance_amount) <= shift.variance_threshold:
        shift.status = "closed"
        shift.save(
            update_fields=[
                "closed_at",
                "closed_by",
                "declared_cash_total",
                "expected_cash_total",
                "variance_amount",
                "status",
                "updated_at",
            ]
        )
        _log_financial_event(
            request,
            action="billing.shift.close",
            object_type="cashier_shift",
            object_id=shift.pk,
            after={
                "status": shift.status,
                "declared_cash_total": str(shift.declared_cash_total),
                "expected_cash_total": str(shift.expected_cash_total),
                "variance_amount": str(shift.variance_amount),
            },
        )
        messages.success(request, "Shift closed successfully.")
        return redirect("billing:index")

    if not reason:
        messages.error(
            request,
            "Variance exceeds threshold. Provide a reason to submit approval request.",
        )
        return redirect("billing:index")

    shift.status = "pending_approval"
    shift.save(
        update_fields=[
            "closed_at",
            "closed_by",
            "declared_cash_total",
            "expected_cash_total",
            "variance_amount",
            "status",
            "updated_at",
        ]
    )

    approval_request, created = ApprovalRequest.objects.get_or_create(
        branch=shift.branch,
        approval_type="shift_variance",
        cashier_shift=shift,
        status="pending",
        defaults={
            "requested_by": shift.opened_by,
            "reason": reason,
            "from_status": "open",
            "to_status": "closed",
        },
    )
    if not created:
        approval_request.reason = reason
        approval_request.save(update_fields=["reason", "updated_at"])

    _log_financial_event(
        request,
        action="billing.shift.close.pending_approval",
        object_type="cashier_shift",
        object_id=shift.pk,
        after={
            "status": shift.status,
            "declared_cash_total": str(shift.declared_cash_total),
            "expected_cash_total": str(shift.expected_cash_total),
            "variance_amount": str(shift.variance_amount),
            "approval_request": approval_request.pk,
        },
        reason=reason,
    )
    messages.warning(request, "Shift variance submitted for approval.")
    return redirect("billing:index")


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def invoice_document(request, pk):
    return_to = _safe_return_url(request)
    invoice = _get_invoice_for_user_or_404(request.user, pk)
    line_items = invoice.line_items.all()
    return render(
        request,
        "billing/invoice_document.html",
        {
            "invoice": invoice,
            "line_items": line_items,
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def quotation_document(request, pk):
    return_to = _safe_return_url(request)
    invoice = _get_invoice_for_user_or_404(request.user, pk)
    line_items = invoice.line_items.all()
    return render(
        request,
        "billing/quotation_document.html",
        {
            "invoice": invoice,
            "line_items": line_items,
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def receipt(request, pk):
    return_to = _safe_return_url(request)
    invoice = _get_invoice_for_user_or_404(request.user, pk)
    line_items = invoice.line_items.all()
    receipts = invoice.receipts.order_by("-created_at")[:3]
    return render(
        request,
        "billing/receipt.html",
        {
            "invoice": invoice,
            "line_items": line_items,
            "receipts": receipts,
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def receipt_detail(request, receipt_pk):
    return_to = _safe_return_url(request)
    rcpt = get_object_or_404(Receipt, pk=receipt_pk)
    scoped = branch_queryset_for_user(
        request.user, Receipt.objects.filter(pk=receipt_pk)
    )
    if not scoped.exists():
        raise Http404("Receipt not found")
    invoice = rcpt.invoice
    line_items = invoice.line_items.all()
    return render(
        request,
        "billing/receipt_detail.html",
        {
            "receipt": rcpt,
            "invoice": invoice,
            "line_items": line_items,
            "return_to": return_to,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def invoices(request):
    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "all").strip().lower()

    queryset = branch_queryset_for_user(
        request.user,
        Invoice.objects.select_related("patient", "cashier").order_by("-created_at"),
    )

    if status in {"pending", "paid", "partial", "post_payment"}:
        queryset = queryset.filter(payment_status=status)
    else:
        status = "all"

    if query:
        queryset = queryset.filter(
            Q(invoice_number__icontains=query)
            | Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
        )

    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "billing/invoices.html",
        {
            "invoices": page,
            "query": query,
            "status": status,
        },
    )


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def create_invoice(request):
    # Logic to create an invoice when a request is initiated
    pass


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "update")
def update_payment(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    payment_status = request.POST.get("payment_status")
    payment_method = request.POST.get("payment_method")
    transaction_id = request.POST.get("transaction_id", None)

    if payment_method != "cash" and not transaction_id:
        return JsonResponse(
            {"error": "Transaction ID is required for non-cash payments."}, status=400
        )

    if payment_status == "paid":
        # Generate full payment receipt
        Receipt.objects.create(invoice=invoice, receipt_type="full")
    elif payment_status == "partial":
        # Generate partial payment receipt
        Receipt.objects.create(invoice=invoice, receipt_type="partial")
    elif payment_status == "post_payment":
        # Add payments to post-payable invoice
        pass

    return redirect("billing:detail", invoice_id=invoice.pk)


@login_required
@role_required("receptionist", "cashier", "system_admin", "director")
@module_permission_required("billing", "view")
def receipts(request):
    query = (request.GET.get("q") or "").strip()
    queryset = branch_queryset_for_user(
        request.user,
        Receipt.objects.select_related("invoice", "invoice__patient").order_by(
            "-created_at"
        ),
    )
    if query:
        queryset = queryset.filter(
            Q(receipt_number__icontains=query)
            | Q(invoice__patient__first_name__icontains=query)
            | Q(invoice__patient__last_name__icontains=query)
        )
    paginator = Paginator(queryset, 25)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "billing/receipts.html", {"receipts": page, "query": query})
