from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem, Receipt
from apps.inventory.models import StockTransfer
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.pharmacy.forms import (
    DispenseForm,
    MedicalStoreRequestForm,
    PrescriptionVisitSelectForm,
    WalkInCustomerForm,
    walkin_line_formset_factory,
)
from apps.pharmacy.models import (
    DispenseRecord,
    MedicalStoreRequest,
    Medicine,
    PharmacyRequest,
    PharmacyShift,
    WalkInSale,
    WalkInSaleLine,
)
from apps.pharmacy.services import (
    available_medicines_queryset,
    sync_branch_medicine_catalog,
)
from apps.visits.services import transition_visit


def _paid_dispense_filter(user):
    """Return a Q filter that keeps only dispense records whose specific
    invoice line item is paid, or records with no visit at all."""
    cleared_pharmacy_ids = InvoiceLineItem.objects.filter(
        source_model="pharmacy",
        invoice__payment_status__in=["paid", "post_payment"],
    ).values_list("source_id", flat=True)
    return Q(visit__isnull=True) | Q(pk__in=cleared_pharmacy_ids)


def _is_pharmacy_request_payment_cleared(pharmacy_request):
    return InvoiceLineItem.objects.filter(
        source_model="pharmacy_request",
        source_id=pharmacy_request.pk,
        invoice__payment_status__in=["paid", "post_payment"],
        cashier_authorized=True,
    ).exists()


@login_required
@role_required("pharmacist", "nurse", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def index(request):
    if request.user.branch_id:
        sync_branch_medicine_catalog(request.user.branch)

    query = request.GET.get("q", "").strip()

    medicines_qs = branch_queryset_for_user(
        request.user, available_medicines_queryset().order_by("name")
    )
    if query:
        medicines_qs = medicines_qs.filter(
            Q(name__icontains=query)
            | Q(category__icontains=query)
            | Q(strength__icontains=query)
            | Q(dosage_form__icontains=query)
            | Q(manufacturer__icontains=query)
            | Q(inventory_item__generic_name__icontains=query)
        )
    medicines = medicines_qs[:50]

    low_stock = branch_queryset_for_user(
        request.user,
        available_medicines_queryset()
        .filter(stock_quantity__lte=10)
        .order_by("stock_quantity", "name"),
    )[:10]

    today = timezone.now().date()
    in_30_days = today + timedelta(days=30)
    expiring = branch_queryset_for_user(
        request.user,
        available_medicines_queryset()
        .filter(expiry_date__gte=today, expiry_date__lte=in_30_days)
        .order_by("expiry_date", "name"),
    )[:10]

    expired = branch_queryset_for_user(
        request.user,
        Medicine.objects.filter(expiry_date__lt=today).order_by("expiry_date", "name"),
    )[:10]

    recent_dispenses = branch_queryset_for_user(
        request.user,
        DispenseRecord.objects.select_related(
            "patient", "medicine", "dispensed_by", "prescribed_by"
        )
        .filter(_paid_dispense_filter(request.user))
        .order_by("-dispensed_at"),
    )[:15]

    recent_store_requests = branch_queryset_for_user(
        request.user,
        MedicalStoreRequest.objects.select_related(
            "requested_by", "handled_by", "item", "stock_item"
        ).order_by("-created_at"),
    )[:10]

    # Pending pharmacy requests from doctors
    pending_rx = list(
        branch_queryset_for_user(
            request.user,
            PharmacyRequest.objects.select_related(
                "patient", "visit", "medicine", "requested_by"
            )
            .filter(status="requested")
            .order_by("-date_requested"),
        )[:50]
    )
    for pr in pending_rx:
        pr.payment_cleared = _is_pharmacy_request_payment_cleared(pr)

    # Pharmacy shift info
    current_shift = None
    if request.user.branch_id:
        current_shift = _get_open_pharmacy_shift(request.user)

    # Pending walk-in sales
    pending_walkin_sales = branch_queryset_for_user(
        request.user,
        WalkInSale.objects.filter(status__in=["pending_payment", "cleared"])
        .prefetch_related("lines__medicine")
        .order_by("-created_at"),
    )[:10]

    return render(
        request,
        "pharmacy/index.html",
        {
            "medicines": medicines,
            "low_stock": low_stock,
            "expiring": expiring,
            "expired": expired,
            "recent_dispenses": recent_dispenses,
            "query": query,
            "recent_store_requests": recent_store_requests,
            "pending_rx": pending_rx,
            "current_shift": current_shift,
            "pending_walkin_sales": pending_walkin_sales,
        },
    )


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def create_medicine(request):
    from apps.inventory.models import Item
    from apps.pharmacy.services import sellable_quantity_for_item

    # Build the available-items queryset (same logic as the old form)
    available_qs = (
        Item.objects.filter(
            is_active=True,
            is_department_stock=False,
            batches__quantity_remaining__gt=0,
            batches__exp_date__gte=timezone.localdate(),
        )
        .select_related("category", "brand")
        .distinct()
        .order_by("item_name")
    )
    if getattr(request.user, "branch_id", None):
        available_qs = available_qs.filter(branch_id=request.user.branch_id)

    available_items = list(available_qs[:200])
    # Annotate sellable qty for template
    for itm in available_items:
        itm.sellable_qty = sellable_quantity_for_item(itm)

    errors = []
    if request.method == "POST":
        if not request.user.branch_id:
            errors.append("Your user account has no branch assigned.")
        else:
            item_ids = request.POST.getlist("item_ids")
            quantities = request.POST.getlist("quantities")
            notes = request.POST.get("notes", "").strip()

            if not item_ids:
                errors.append("Please add at least one item to the request.")
            else:
                created = 0
                for raw_id, raw_qty in zip(item_ids, quantities):
                    try:
                        item_id = int(raw_id)
                        qty = int(raw_qty)
                    except (ValueError, TypeError):
                        continue
                    if qty <= 0:
                        continue
                    item = (
                        Item.objects.filter(
                            pk=item_id,
                            is_active=True,
                            is_department_stock=False,
                        )
                        .select_related("category")
                        .first()
                    )
                    if not item:
                        continue
                    avail = sellable_quantity_for_item(item)
                    if qty > avail:
                        errors.append(
                            f"{item.item_name}: requested {qty} but only {avail} available."
                        )
                        continue
                    MedicalStoreRequest.objects.create(
                        branch=request.user.branch,
                        requested_by=request.user,
                        requested_for="pharmacy",
                        item=item,
                        medicine_name=item.item_name,
                        category=item.category.name if item.category else "",
                        quantity_requested=qty,
                        notes=notes,
                    )
                    created += 1

                if created and not errors:
                    messages.success(
                        request,
                        f"{created} request(s) submitted to medical stores.",
                    )
                    return redirect("pharmacy:index")
                elif created and errors:
                    messages.warning(
                        request,
                        f"{created} request(s) submitted. Some items had issues.",
                    )

    return render(
        request,
        "pharmacy/medicine_form.html",
        {
            "available_items": available_items,
            "errors": errors,
            "page_title": "Request Medicine From Medical Stores",
            "section_label": "Pharmacy",
            "section_index_url": "pharmacy:index",
        },
    )


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def dispense(request):
    if request.user.branch_id:
        sync_branch_medicine_catalog(request.user.branch)

    if request.method == "POST":
        form = DispenseForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                record = form.save(commit=False)
                record.branch = request.user.branch
                record.dispensed_by = request.user
                record.unit_price = record.medicine.current_selling_price

                matched_request = None
                if record.visit_id and record.patient_id:
                    matched_request = branch_queryset_for_user(
                        request.user,
                        PharmacyRequest.objects.select_related("medicine")
                        .filter(
                            visit_id=record.visit_id,
                            patient_id=record.patient_id,
                            medicine_id=record.medicine_id,
                            status="requested",
                        )
                        .order_by("date_requested"),
                    ).first()
                    if matched_request and not _is_pharmacy_request_payment_cleared(
                        matched_request
                    ):
                        messages.error(
                            request,
                            "Cashier payment clearance is pending for this pharmacy request.",
                        )
                        return redirect("pharmacy:dispense")

                record.save()
                if matched_request:
                    matched_request.status = "dispensed"
                    matched_request.save(update_fields=["status", "updated_at"])
                    for line_item in InvoiceLineItem.objects.filter(
                        source_model="pharmacy_request",
                        source_id=matched_request.pk,
                    ):
                        line_item.unit_cost = record.unit_cost_snapshot
                        line_item.total_cost = record.total_cost_snapshot
                        line_item.profit_amount = (
                            line_item.amount - record.total_cost_snapshot
                        )
                        line_item.save(
                            update_fields=[
                                "unit_cost",
                                "total_cost",
                                "profit_amount",
                                "updated_at",
                            ]
                        )

                if record.visit:
                    pending_requests = PharmacyRequest.objects.filter(
                        visit=record.visit,
                        status="requested",
                    ).exists()
                    if pending_requests:
                        transition_visit(record.visit, "waiting_pharmacy", request.user)
                    else:
                        transition_visit(record.visit, "waiting_doctor", request.user)
                return redirect("pharmacy:prescriptions")
    else:
        form = DispenseForm(user=request.user)

    return render(
        request,
        "pharmacy/dispense_form.html",
        {
            "form": form,
            "page_title": "Dispense Drug",
            "submit_label": "Dispense",
        },
    )


# ── Walk-in multi-item dispensing (creates pending sale for cashier) ─
@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def dispense_walkin(request):
    if request.user.branch_id:
        sync_branch_medicine_catalog(request.user.branch)

    if request.method == "POST":
        customer_form = WalkInCustomerForm(request.POST)
        line_formset = walkin_line_formset_factory(
            user=request.user, data=request.POST, extra=0
        )

        if customer_form.is_valid() and line_formset.is_valid():
            if not request.user.branch_id:
                customer_form.add_error(
                    None, "Your user account has no branch assigned."
                )
            else:
                walk_in_name = customer_form.cleaned_data["walk_in_name"]
                walk_in_phone = customer_form.cleaned_data["walk_in_phone"]

                sale = WalkInSale.objects.create(
                    branch=request.user.branch,
                    customer_name=walk_in_name,
                    customer_phone=walk_in_phone,
                    created_by=request.user,
                    status="pending_payment",
                )
                sale_lines = []
                for line_form in line_formset:
                    medicine = line_form.cleaned_data.get("medicine")
                    quantity = line_form.cleaned_data.get("quantity")
                    if not medicine or not quantity:
                        continue
                    sl = WalkInSaleLine.objects.create(
                        branch=request.user.branch,
                        sale=sale,
                        medicine=medicine,
                        quantity=quantity,
                        unit_price=medicine.current_selling_price,
                    )
                    sale_lines.append(sl)

                if sale_lines:
                    sale.recalculate_total()

                    # ── Create Invoice + line items for billing ──
                    from apps.billing.views import _generate_invoice_number

                    branch = request.user.branch
                    invoice = Invoice.objects.create(
                        branch=branch,
                        invoice_number=_generate_invoice_number(branch),
                        patient=None,
                        walk_in_customer_name=walk_in_name,
                        walk_in_customer_phone=walk_in_phone,
                        services="\n".join(
                            f"{sl.medicine.name} x{sl.quantity} - {sl.line_total}"
                            for sl in sale_lines
                        ),
                        total_amount=sale.total_amount,
                        payment_method="cash",
                        payment_status="pending",
                        cashier=request.user,
                    )
                    for sl in sale_lines:
                        InvoiceLineItem.objects.create(
                            invoice=invoice,
                            branch=branch,
                            service_type="pharmacy",
                            description=f"{sl.medicine.name} x{sl.quantity} (Walk-In)",
                            amount=sl.line_total,
                            paid_amount=Decimal("0.00"),
                            payment_status="pending",
                            unit_cost=Decimal("0.00"),
                            total_cost=Decimal("0.00"),
                            profit_amount=sl.line_total,
                            source_model="walkin_sale_line",
                            source_id=sl.pk,
                        )

                    sale.invoice = invoice
                    sale.save(update_fields=["total_amount", "invoice", "updated_at"])
                    messages.success(
                        request,
                        f"Walk-in sale created for {walk_in_name} ({len(sale_lines)} item(s)). "
                        f"Invoice {invoice.invoice_number} sent to billing for payment.",
                    )
                    return redirect("pharmacy:pending_walkins")
                else:
                    sale.delete()
                    customer_form.add_error(None, "Add at least one medicine line.")
    else:
        customer_form = WalkInCustomerForm()
        line_formset = walkin_line_formset_factory(user=request.user, extra=1)

    return render(
        request,
        "pharmacy/dispense_walkin.html",
        {
            "customer_form": customer_form,
            "line_formset": line_formset,
            "page_title": "Walk-In Sale — Send to Cashier",
        },
    )


# ── Prescription dispensing (doctor-prescribed items) ──────────
@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def dispense_prescription(request):
    if request.user.branch_id:
        sync_branch_medicine_catalog(request.user.branch)

    visit_form = PrescriptionVisitSelectForm(user=request.user)
    pending_requests = []
    selected_visit = None

    # Step 1: visit selection via GET param
    visit_id = request.GET.get("visit") or request.POST.get("visit_id")
    if visit_id:
        from apps.visits.models import Visit as VisitModel

        selected_visit = branch_queryset_for_user(
            request.user,
            VisitModel.objects.select_related("patient").filter(
                pk=visit_id, check_out_time__isnull=True
            ),
        ).first()

    if selected_visit:
        pending_requests = list(
            branch_queryset_for_user(
                request.user,
                PharmacyRequest.objects.select_related("medicine", "requested_by")
                .filter(visit=selected_visit, status="requested")
                .order_by("date_requested"),
            )
        )

    # Step 2: POST — dispense selected items
    if request.method == "POST" and selected_visit:
        selected_ids = request.POST.getlist("dispense_ids")
        if not selected_ids:
            messages.warning(request, "No items selected for dispensing.")
        else:
            dispensed_count = 0
            for pr in pending_requests:
                if str(pr.pk) not in selected_ids:
                    continue

                if not _is_pharmacy_request_payment_cleared(pr):
                    messages.error(
                        request,
                        f"Payment not cleared for {pr.medicine.name}. Skipped.",
                    )
                    continue

                record = DispenseRecord(
                    branch=request.user.branch,
                    sale_type=DispenseRecord.SALE_TYPE_PRESCRIPTION,
                    patient=selected_visit.patient,
                    visit=selected_visit,
                    medicine=pr.medicine,
                    quantity=pr.quantity,
                    prescribed_by=pr.requested_by,
                    prescription_notes=pr.notes,
                    dispensed_by=request.user,
                    unit_price=pr.medicine.current_selling_price,
                )
                try:
                    record.save()
                except Exception as exc:
                    messages.error(
                        request,
                        f"Error dispensing {pr.medicine.name}: {exc}",
                    )
                    continue

                pr.status = "dispensed"
                pr.save(update_fields=["status", "updated_at"])

                for line_item in InvoiceLineItem.objects.filter(
                    source_model="pharmacy_request",
                    source_id=pr.pk,
                ):
                    line_item.unit_cost = record.unit_cost_snapshot
                    line_item.total_cost = record.total_cost_snapshot
                    line_item.profit_amount = (
                        line_item.amount - record.total_cost_snapshot
                    )
                    line_item.save(
                        update_fields=[
                            "unit_cost",
                            "total_cost",
                            "profit_amount",
                            "updated_at",
                        ]
                    )
                dispensed_count += 1

            if dispensed_count:
                still_pending = PharmacyRequest.objects.filter(
                    visit=selected_visit, status="requested"
                ).exists()
                if still_pending:
                    transition_visit(selected_visit, "waiting_pharmacy", request.user)
                else:
                    transition_visit(selected_visit, "waiting_doctor", request.user)
                messages.success(
                    request,
                    f"{dispensed_count} item(s) dispensed for {selected_visit.patient}.",
                )
                return redirect("pharmacy:prescriptions")

        # Refresh pending list after partial dispense
        pending_requests = list(
            branch_queryset_for_user(
                request.user,
                PharmacyRequest.objects.select_related("medicine", "requested_by")
                .filter(visit=selected_visit, status="requested")
                .order_by("date_requested"),
            )
        )

    # Annotate each pending request with payment status for display
    for pr in pending_requests:
        pr.payment_cleared = _is_pharmacy_request_payment_cleared(pr)

    return render(
        request,
        "pharmacy/dispense_prescription.html",
        {
            "visit_form": visit_form,
            "pending_requests": pending_requests,
            "selected_visit": selected_visit,
            "page_title": "Prescription Dispensing",
        },
    )


@login_required
@role_required("pharmacist", "doctor", "nurse", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def prescriptions(request):
    if request.user.branch_id:
        sync_branch_medicine_catalog(request.user.branch)

    queryset = branch_queryset_for_user(
        request.user,
        DispenseRecord.objects.select_related(
            "patient", "medicine", "dispensed_by", "prescribed_by"
        )
        .filter(_paid_dispense_filter(request.user))
        .order_by("-dispensed_at"),
    )

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__patient_id__icontains=query)
            | Q(medicine__name__icontains=query)
        )

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "pharmacy/prescriptions.html",
        {
            "records": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
        },
    )


@login_required
@role_required(
    "pharmacist", "nurse", "cashier", "receptionist", "system_admin", "director"
)
@module_permission_required("pharmacy", "view")
def pharmacy_receipts(request):
    """Pharmacy-specific receipts filtered from billing receipts."""
    query = request.GET.get("q", "").strip()
    method = request.GET.get("method", "").strip()
    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    receipt_type = request.GET.get("type", "").strip()

    # Receipts whose invoice has at least one pharmacy line item
    pharmacy_invoice_ids = InvoiceLineItem.objects.filter(
        service_type="pharmacy",
    ).values_list("invoice_id", flat=True)

    queryset = branch_queryset_for_user(
        request.user,
        Receipt.objects.select_related("invoice", "patient", "received_by")
        .filter(invoice_id__in=pharmacy_invoice_ids)
        .order_by("-created_at"),
    )

    if query:
        queryset = queryset.filter(
            Q(receipt_number__icontains=query)
            | Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(invoice__invoice_number__icontains=query)
        )
    if method:
        queryset = queryset.filter(payment_method=method)
    if receipt_type:
        queryset = queryset.filter(receipt_type=receipt_type)
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "pharmacy/pharmacy_receipts.html",
        {
            "receipts": page_obj,
            "query": query,
            "method": method,
            "date_from": date_from,
            "date_to": date_to,
            "receipt_type": receipt_type,
        },
    )


@login_required
@role_required(
    "pharmacist", "nurse", "cashier", "receptionist", "system_admin", "director"
)
@module_permission_required("pharmacy", "view")
def pharmacy_receipt_detail(request, receipt_pk):
    """View a single receipt without leaving the pharmacy module."""
    rcpt = get_object_or_404(Receipt, pk=receipt_pk)
    scoped = branch_queryset_for_user(
        request.user, Receipt.objects.filter(pk=receipt_pk)
    )
    if not scoped.exists():
        from django.http import Http404

        raise Http404("Receipt not found")
    invoice = rcpt.invoice
    line_items = invoice.line_items.all()
    return render(
        request,
        "pharmacy/receipt_detail.html",
        {
            "receipt": rcpt,
            "invoice": invoice,
            "line_items": line_items,
        },
    )


@login_required
@role_required("pharmacist", "nurse", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def pharmacy_transfer_report(request):
    """Pharmacy-scoped stock transfer report — shows transfers
    involving the pharmacy store without routing to inventory."""
    today = timezone.localdate()
    default_start = today - timedelta(days=30)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    try:
        date_from = timezone.datetime.strptime(date_from, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        date_from = default_start
    try:
        date_to = timezone.datetime.strptime(date_to, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        date_to = today
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    pharmacy_transfers = branch_queryset_for_user(
        request.user,
        StockTransfer.objects.select_related(
            "source_item",
            "source_batch",
            "destination_item",
            "destination_batch",
            "transferred_by",
            "store_request",
        )
        .filter(
            transferred_at__date__range=(date_from, date_to),
        )
        .filter(
            Q(source_item__store_department="pharmacy")
            | Q(destination_item__store_department="pharmacy")
        )
        .order_by("-transferred_at"),
    )[:200]

    summary_qs = branch_queryset_for_user(
        request.user,
        StockTransfer.objects.filter(
            transferred_at__date__range=(date_from, date_to),
        ).filter(
            Q(source_item__store_department="pharmacy")
            | Q(destination_item__store_department="pharmacy")
        ),
    )
    summary = summary_qs.aggregate(
        total_qty=Sum("quantity"),
        total_cost_value=Sum(
            F("quantity") * F("unit_cost"),
            output_field=models.DecimalField(),
        ),
        total_retail_value=Sum(
            F("quantity") * F("selling_price_per_unit"),
            output_field=models.DecimalField(),
        ),
    )

    return render(
        request,
        "pharmacy/transfer_report.html",
        {
            "transfers": pharmacy_transfers,
            "date_from": date_from,
            "date_to": date_to,
            "summary": {
                "total_qty": summary["total_qty"] or 0,
                "total_cost_value": summary["total_cost_value"] or Decimal("0.00"),
                "total_retail_value": summary["total_retail_value"] or Decimal("0.00"),
            },
        },
    )


# ── Pending walk-in sales (pharmacy view — dispense only) ─────
@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def pending_walkins(request):
    queryset = branch_queryset_for_user(
        request.user,
        WalkInSale.objects.select_related("invoice")
        .prefetch_related("lines__medicine")
        .filter(status__in=["pending_payment", "cleared"])
        .order_by("-created_at"),
    )
    return render(request, "pharmacy/pending_walkins.html", {"sales": queryset})


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def dispense_walkin_cleared(request, sale_pk):
    """Dispense medicines for a walk-in sale whose invoice has been paid."""
    sale = get_object_or_404(WalkInSale, pk=sale_pk)
    scoped = branch_queryset_for_user(
        request.user, WalkInSale.objects.filter(pk=sale_pk)
    )
    if not scoped.exists():
        from django.http import Http404

        raise Http404("Walk-in sale not found")

    # Check that the invoice is paid
    if not sale.invoice or sale.invoice.payment_status not in ("paid", "post_payment"):
        messages.error(
            request,
            "Payment has not been completed for this sale. The invoice must be paid before dispensing.",
        )
        return redirect("pharmacy:pending_walkins")

    if sale.status == "dispensed":
        messages.info(request, "This sale has already been dispensed.")
        return redirect("pharmacy:pending_walkins")

    if request.method == "POST":
        if request.user.branch_id:
            sync_branch_medicine_catalog(request.user.branch)

        dispensed_count = 0
        errors = []
        for line in sale.lines.select_related("medicine"):
            record = DispenseRecord(
                branch=sale.branch,
                sale_type=DispenseRecord.SALE_TYPE_WALK_IN,
                medicine=line.medicine,
                quantity=line.quantity,
                walk_in_name=sale.customer_name,
                walk_in_phone=sale.customer_phone,
                dispensed_by=request.user,
                unit_price=line.unit_price,
            )
            try:
                record.save()
                dispensed_count += 1

                # Update the matching invoice line item with actual cost/profit
                for inv_line in InvoiceLineItem.objects.filter(
                    source_model="walkin_sale_line",
                    source_id=line.pk,
                ):
                    inv_line.unit_cost = record.unit_cost_snapshot
                    inv_line.total_cost = record.total_cost_snapshot
                    inv_line.profit_amount = (
                        inv_line.amount - record.total_cost_snapshot
                    )
                    inv_line.stock_deducted_at = timezone.now()
                    inv_line.save(
                        update_fields=[
                            "unit_cost",
                            "total_cost",
                            "profit_amount",
                            "stock_deducted_at",
                            "updated_at",
                        ]
                    )
            except Exception as exc:
                errors.append(f"{line.medicine.name}: {exc}")

        if dispensed_count:
            sale.status = "dispensed"
            sale.dispensed_at = timezone.now()
            sale.cleared_by = sale.invoice.cashier if sale.invoice else None
            sale.cleared_at = sale.cleared_at or timezone.now()
            sale.save(
                update_fields=[
                    "status",
                    "dispensed_at",
                    "cleared_by",
                    "cleared_at",
                    "updated_at",
                ]
            )
            messages.success(
                request,
                f"{dispensed_count} medicine(s) dispensed to {sale.customer_name}.",
            )
        for err in errors:
            messages.error(request, err)
        return redirect("pharmacy:pending_walkins")

    return redirect("pharmacy:pending_walkins")


# ── Pharmacy Shift Management ─────────────────────────────────
def _get_open_pharmacy_shift(user):
    return PharmacyShift.objects.filter(
        branch=user.branch,
        opened_by=user,
        status="open",
    ).first()


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def open_shift(request):
    existing = _get_open_pharmacy_shift(request.user)
    if existing:
        messages.info(request, "You already have an open pharmacy shift.")
        return redirect("pharmacy:index")

    if request.method == "POST":
        if not request.user.branch_id:
            messages.error(request, "Your account has no branch assigned.")
            return redirect("pharmacy:index")
        PharmacyShift.objects.create(
            branch=request.user.branch,
            opened_by=request.user,
            status="open",
        )
        messages.success(request, "Pharmacy shift opened.")
        return redirect("pharmacy:index")

    return render(request, "pharmacy/open_shift.html")


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "update")
def close_shift(request, shift_pk):
    shift = get_object_or_404(PharmacyShift, pk=shift_pk)
    scoped = branch_queryset_for_user(
        request.user, PharmacyShift.objects.filter(pk=shift_pk)
    )
    if not scoped.exists():
        from django.http import Http404

        raise Http404("Shift not found")

    if shift.status != "open":
        messages.info(request, "This shift is already closed.")
        return redirect("pharmacy:shift_report", shift_pk=shift.pk)

    if request.method == "POST":
        notes = (request.POST.get("notes") or "").strip()
        shift.status = "closed"
        shift.closed_at = timezone.now()
        shift.closed_by = request.user
        shift.notes = notes
        shift.save(
            update_fields=[
                "status",
                "closed_at",
                "closed_by",
                "notes",
                "updated_at",
            ]
        )
        messages.success(request, "Pharmacy shift closed. View the shift report below.")
        return redirect("pharmacy:shift_report", shift_pk=shift.pk)

    # Show confirmation with summary
    dispenses = shift.get_dispenses()
    return render(
        request,
        "pharmacy/close_shift.html",
        {
            "shift": shift,
            "dispense_count": dispenses.count(),
        },
    )


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def shift_report(request, shift_pk):
    shift = get_object_or_404(PharmacyShift, pk=shift_pk)
    scoped = branch_queryset_for_user(
        request.user, PharmacyShift.objects.filter(pk=shift_pk)
    )
    if not scoped.exists():
        from django.http import Http404

        raise Http404("Shift not found")

    dispenses = shift.get_dispenses().order_by("dispensed_at")

    # Summary stats
    total_dispenses = dispenses.count()
    walkin_count = dispenses.filter(sale_type=DispenseRecord.SALE_TYPE_WALK_IN).count()
    prescription_count = dispenses.filter(
        sale_type=DispenseRecord.SALE_TYPE_PRESCRIPTION
    ).count()

    agg = dispenses.aggregate(
        total_revenue=Sum(
            F("unit_price") * F("quantity"), output_field=models.DecimalField()
        ),
        total_cost=Sum("total_cost_snapshot"),
        total_profit=Sum("profit_amount"),
        total_items=Sum("quantity"),
    )

    return render(
        request,
        "pharmacy/shift_report.html",
        {
            "shift": shift,
            "dispenses": dispenses,
            "total_dispenses": total_dispenses,
            "walkin_count": walkin_count,
            "prescription_count": prescription_count,
            "total_revenue": agg["total_revenue"] or Decimal("0.00"),
            "total_cost": agg["total_cost"] or Decimal("0.00"),
            "total_profit": agg["total_profit"] or Decimal("0.00"),
            "total_items": agg["total_items"] or 0,
        },
    )


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "view")
def shift_history(request):
    queryset = branch_queryset_for_user(
        request.user,
        PharmacyShift.objects.select_related("opened_by", "closed_by").order_by(
            "-opened_at"
        ),
    )
    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "pharmacy/shift_history.html",
        {
            "shifts": page_obj.object_list,
            "page_obj": page_obj,
        },
    )
