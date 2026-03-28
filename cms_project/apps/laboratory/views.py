from io import BytesIO
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.inventory.forms import (
    ServiceConsumptionCorrectionForm,
    build_service_consumable_formset,
)
from apps.inventory.services import (
    has_service_consumptions,
    record_selected_service_items,
    reverse_service_consumptions,
    summarized_service_consumptions,
)
from apps.laboratory.forms import LAB_TEST_CHOICES, LabRequestForm, LabResultForm
from apps.laboratory.models import LabRequest
from apps.pharmacy.forms import MedicalStoreRequestForm
from apps.pharmacy.models import MedicalStoreRequest
from apps.settingsapp.services import get_lab_fee
from apps.visits.services import transition_visit


def _generate_invoice_number():
    return f"INV-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"


def _is_lab_request_payment_cleared(lab_request):
    return InvoiceLineItem.objects.filter(
        source_model="lab",
        source_id=lab_request.pk,
        invoice__payment_status="paid",
    ).exists()


def _lab_consumption_state(lab_request):
    rows, total_cost = summarized_service_consumptions(
        lab_request.branch,
        "lab",
        lab_request.pk,
    )
    return rows, total_cost, bool(rows)


def _can_correct_consumables(user):
    return user.is_superuser or user.role in {"system_admin", "director"}


def _build_lab_result_pdf_bytes(lab_request, payment_cleared):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Laboratory Result Report")
    y -= 16
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, "Clinical Result Record")
    y -= 20

    rows = [
        (
            "Patient",
            f"{lab_request.patient.first_name} {lab_request.patient.last_name}",
        ),
        ("Visit Number", lab_request.visit.visit_number if lab_request.visit else "-"),
        ("Test Type", lab_request.test_type),
        ("Status", lab_request.get_status_display()),
        (
            "Requested By",
            lab_request.requested_by.get_full_name()
            or lab_request.requested_by.username,
        ),
        (
            "Processed By",
            (
                lab_request.technician.get_full_name()
                or lab_request.technician.username
                if lab_request.technician
                else "-"
            ),
        ),
        ("Requested On", str(lab_request.date)),
        ("Sample Collected", "Yes" if lab_request.sample_collected else "No"),
        ("Payment Cleared", "Yes" if payment_cleared else "No"),
    ]
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(160, y, str(value))
        y -= 14

    y -= 8
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Results")
    y -= 14
    pdf.setFont("Helvetica", 10)
    for line in (lab_request.results or "No results uploaded yet.").splitlines()[:25]:
        pdf.drawString(40, y, line[:120])
        y -= 12
        if y < 80:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 10)

    y -= 6
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(40, y, "Lab Remarks")
    y -= 14
    pdf.setFont("Helvetica", 10)
    for line in (lab_request.comments or "No comments.").splitlines()[:20]:
        pdf.drawString(40, y, line[:120])
        y -= 12
        if y < 80:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 10)

    y -= 18
    pdf.drawString(40, y, "Lab Signature: ____________________________")
    y -= 16
    pdf.drawString(40, y, "Doctor Acknowledgement: ____________________________")

    pdf.save()
    data = buffer.getvalue()
    buffer.close()
    return data


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "view")
def index(request):
    cleared_lab_ids = InvoiceLineItem.objects.filter(
        source_model="lab",
        invoice__payment_status="paid",
    ).values_list("source_id", flat=True)

    queryset = branch_queryset_for_user(
        request.user,
        LabRequest.objects.select_related("patient", "requested_by", "technician")
        .filter(pk__in=cleared_lab_ids)
        .order_by("-date"),
    )
    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    recent_store_requests = branch_queryset_for_user(
        request.user,
        MedicalStoreRequest.objects.select_related("requested_by", "item")
        .filter(requested_for="laboratory")
        .order_by("-created_at"),
    )[:10]
    return render(
        request,
        "laboratory/index.html",
        {
            "requests": page_obj.object_list,
            "page_obj": page_obj,
            "lab_tests": [label for value, label in LAB_TEST_CHOICES if value],
            "result_feed_mode": False,
            "recent_store_requests": recent_store_requests,
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "update")
def result_feed_queue(request):
    cleared_lab_ids = InvoiceLineItem.objects.filter(
        source_model="lab",
        invoice__payment_status="paid",
    ).values_list("source_id", flat=True)

    queryset = branch_queryset_for_user(
        request.user,
        LabRequest.objects.select_related("patient", "requested_by", "technician")
        .filter(pk__in=cleared_lab_ids)
        .exclude(status="reviewed")
        .order_by("date"),
    )
    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    recent_store_requests = branch_queryset_for_user(
        request.user,
        MedicalStoreRequest.objects.select_related("requested_by", "item")
        .filter(requested_for="laboratory")
        .order_by("-created_at"),
    )[:10]
    return render(
        request,
        "laboratory/index.html",
        {
            "requests": page_obj.object_list,
            "page_obj": page_obj,
            "lab_tests": [label for value, label in LAB_TEST_CHOICES if value],
            "result_feed_mode": True,
            "recent_store_requests": recent_store_requests,
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "update")
def request_medical_store_stock(request):
    if request.method == "POST":
        form = MedicalStoreRequestForm(
            request.POST,
            user=request.user,
            requested_for="laboratory",
        )
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                store_request = form.save(commit=False)
                store_request.branch = request.user.branch
                store_request.requested_by = request.user
                store_request.requested_for = "laboratory"
                item = form.cleaned_data["item"]
                store_request.item = item
                store_request.medicine_name = item.item_name
                store_request.category = item.category.name
                store_request.save()
                messages.success(
                    request,
                    "Laboratory stock request submitted to medical stores.",
                )
                return redirect("laboratory:index")
    else:
        form = MedicalStoreRequestForm(user=request.user, requested_for="laboratory")

    return render(
        request,
        "pharmacy/medicine_form.html",
        {
            "form": form,
            "page_title": "Request Laboratory Stock From Medical Stores",
            "submit_label": "Submit Laboratory Request",
            "section_label": "Laboratory",
            "section_index_url": "laboratory:index",
        },
    )


def _get_lab_request_for_user_or_404(user, pk):
    instance = (
        LabRequest.objects.select_related(
            "patient", "requested_by", "technician", "branch"
        )
        .filter(pk=pk)
        .first()
    )
    if not instance:
        raise Http404("Lab request not found")

    scoped = branch_queryset_for_user(user, LabRequest.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Lab request not found")
    return instance


@login_required
@role_required("doctor")
@module_permission_required("laboratory", "create")
def create_request(request):
    if request.method == "POST":
        form = LabRequestForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                lab_request = form.save(commit=False)
                lab_request.branch = request.user.branch
                lab_request.requested_by = request.user
                lab_request.status = "requested"
                lab_request.save()
                if lab_request.visit:
                    transition_visit(
                        lab_request.visit,
                        "billing_queue",
                        request.user,
                        notes="Lab request created and forwarded to cashier for payment.",
                    )

                service_fee = get_lab_fee(lab_request.test_type)
                invoice = Invoice.objects.create(
                    branch=lab_request.branch,
                    invoice_number=_generate_invoice_number(),
                    patient=lab_request.patient,
                    visit=lab_request.visit,
                    services=f"Lab Test - {lab_request.test_type}",
                    total_amount=service_fee,
                    payment_method="cash",
                    payment_status="pending",
                    cashier=request.user,
                )
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    branch=invoice.branch,
                    service_type="lab",
                    description=f"Lab Test - {lab_request.test_type}",
                    amount=service_fee,
                    unit_cost=Decimal("0.00"),
                    total_cost=Decimal("0.00"),
                    profit_amount=Decimal("0.00"),
                    source_model="lab",
                    source_id=lab_request.id,
                )
                return redirect("billing:detail", pk=invoice.pk)
    else:
        form = LabRequestForm(user=request.user)

    return render(
        request,
        "laboratory/request_form.html",
        {
            "form": form,
            "page_title": "Create Lab Request",
            "submit_label": "Submit Lab Request",
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "update")
def record_consumables(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    if not _is_lab_request_payment_cleared(lab_request):
        raise Http404("Lab request is awaiting cashier payment clearance.")

    consumption_rows, consumption_total_cost, consumables_recorded = (
        _lab_consumption_state(lab_request)
    )
    if consumables_recorded:
        messages.info(
            request,
            "Consumables have already been recorded for this patient test.",
        )
        return redirect("laboratory:detail", pk=lab_request.pk)

    if request.method == "POST":
        formset = build_service_consumable_formset(
            request.POST,
            branch=lab_request.branch,
            store_department="laboratory",
        )
        if formset.is_valid():
            selections = [
                {
                    "item": form.cleaned_data["item"],
                    "quantity": form.cleaned_data["quantity"],
                }
                for form in formset
                if form.cleaned_data.get("item")
            ]
            try:
                record_selected_service_items(
                    branch=lab_request.branch,
                    service_type="lab",
                    source_model="lab",
                    source_id=lab_request.pk,
                    selections=selections,
                    consumed_by=request.user,
                    store_department="laboratory",
                    reference=(
                        f"Lab request {lab_request.pk} consumables for "
                        f"{lab_request.patient.first_name} {lab_request.patient.last_name}"
                    ),
                )
            except ValidationError as exc:
                formset._non_form_errors = formset.error_class(exc.messages)
            else:
                messages.success(
                    request,
                    "Laboratory consumables captured and departmental cost updated.",
                )
                return redirect("laboratory:detail", pk=lab_request.pk)
    else:
        formset = build_service_consumable_formset(
            branch=lab_request.branch,
            store_department="laboratory",
        )

    return render(
        request,
        "laboratory/consumables_form.html",
        {
            "lab_request": lab_request,
            "formset": formset,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("laboratory", "update")
def correct_consumables(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    consumption_rows, consumption_total_cost, consumables_recorded = (
        _lab_consumption_state(lab_request)
    )
    if not consumables_recorded:
        messages.info(request, "There are no active consumables to correct.")
        return redirect("laboratory:record_consumables", pk=lab_request.pk)

    if request.method == "POST":
        form = ServiceConsumptionCorrectionForm(request.POST)
        if form.is_valid():
            reverse_service_consumptions(
                branch=lab_request.branch,
                source_model="lab",
                source_id=lab_request.pk,
                reversed_by=request.user,
                reason=form.cleaned_data["reason"],
                reference=f"Lab request {lab_request.pk} consumable correction",
            )
            messages.success(
                request,
                "Laboratory consumables reversed. Re-enter the correct consumables now.",
            )
            return redirect("laboratory:record_consumables", pk=lab_request.pk)
    else:
        form = ServiceConsumptionCorrectionForm()

    return render(
        request,
        "laboratory/consumables_correction_form.html",
        {
            "lab_request": lab_request,
            "form": form,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "update")
def update_result(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    if not _is_lab_request_payment_cleared(lab_request):
        raise Http404("Lab request is awaiting cashier payment clearance.")
    if not has_service_consumptions(lab_request.branch, "lab", lab_request.pk):
        messages.warning(
            request,
            "Record apparatus and reagents used before feeding laboratory results.",
        )
        return redirect("laboratory:record_consumables", pk=lab_request.pk)

    consumption_rows, consumption_total_cost, _ = _lab_consumption_state(lab_request)

    if request.method == "POST":
        form = LabResultForm(request.POST, instance=lab_request)
        if form.is_valid():
            updated_request = form.save(commit=False)
            updated_request.technician = request.user
            updated_request.save()
            if updated_request.visit and updated_request.status == "completed":
                transition_visit(updated_request.visit, "waiting_doctor", request.user)
            return redirect("laboratory:detail", pk=updated_request.pk)
    else:
        form = LabResultForm(instance=lab_request)

    return render(
        request,
        "laboratory/result_form.html",
        {
            "form": form,
            "lab_request": lab_request,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
            "page_title": "Upload Lab Results",
            "submit_label": "Save Results",
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "view")
def detail(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    consumption_rows, consumption_total_cost, consumables_recorded = (
        _lab_consumption_state(lab_request)
    )
    return render(
        request,
        "laboratory/detail.html",
        {
            "lab_request": lab_request,
            "payment_cleared": _is_lab_request_payment_cleared(lab_request),
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
            "consumables_recorded": consumables_recorded,
            "can_correct_consumables": _can_correct_consumables(request.user),
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "view")
def print_result(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    return render(
        request,
        "laboratory/report_copy.html",
        {
            "lab_request": lab_request,
            "payment_cleared": _is_lab_request_payment_cleared(lab_request),
            "print_mode": True,
        },
    )


@login_required
@role_required("lab_technician", "system_admin", "director")
@module_permission_required("laboratory", "view")
def download_result_pdf(request, pk):
    lab_request = _get_lab_request_for_user_or_404(request.user, pk)
    payment_cleared = _is_lab_request_payment_cleared(lab_request)
    pdf_bytes = _build_lab_result_pdf_bytes(lab_request, payment_cleared)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    filename = f"lab_result_{lab_request.pk}_{timestamp}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
