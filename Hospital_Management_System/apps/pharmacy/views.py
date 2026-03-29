from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.billing.models import InvoiceLineItem, Receipt
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
        },
    )


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("pharmacy", "create")
def create_medicine(request):
    if request.method == "POST":
        form = MedicalStoreRequestForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                store_request = form.save(commit=False)
                store_request.branch = request.user.branch
                store_request.requested_by = request.user
                store_request.requested_for = "pharmacy"
                item = form.cleaned_data["item"]
                store_request.item = item
                store_request.medicine_name = item.item_name
                store_request.category = item.category.name
                store_request.save()
                messages.success(
                    request,
                    "Request submitted to medical stores under inventory for handling.",
                )
                return redirect("pharmacy:index")
    else:
        form = MedicalStoreRequestForm(user=request.user)

    return render(
        request,
        "pharmacy/medicine_form.html",
        {
            "form": form,
            "page_title": "Request Medicine From Medical Stores",
            "submit_label": "Submit Request",
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


# ── Walk-in multi-item dispensing ──────────────────────────────
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
                dispensed_count = 0

                for line_form in line_formset:
                    medicine = line_form.cleaned_data.get("medicine")
                    quantity = line_form.cleaned_data.get("quantity")
                    if not medicine or not quantity:
                        continue

                    record = DispenseRecord(
                        branch=request.user.branch,
                        sale_type=DispenseRecord.SALE_TYPE_WALK_IN,
                        medicine=medicine,
                        quantity=quantity,
                        walk_in_name=walk_in_name,
                        walk_in_phone=walk_in_phone,
                        dispensed_by=request.user,
                        unit_price=medicine.current_selling_price,
                    )
                    try:
                        record.save()
                        dispensed_count += 1
                    except Exception as exc:
                        customer_form.add_error(
                            None,
                            f"Error dispensing {medicine.name}: {exc}",
                        )

                if dispensed_count and not customer_form.errors:
                    messages.success(
                        request,
                        f"{dispensed_count} medicine(s) dispensed to {walk_in_name}.",
                    )
                    return redirect("pharmacy:prescriptions")
    else:
        customer_form = WalkInCustomerForm()
        line_formset = walkin_line_formset_factory(user=request.user, extra=1)

    return render(
        request,
        "pharmacy/dispense_walkin.html",
        {
            "customer_form": customer_form,
            "line_formset": line_formset,
            "page_title": "Walk-In Dispensing",
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
