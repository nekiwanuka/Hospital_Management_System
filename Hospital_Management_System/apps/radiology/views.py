from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Prefetch, Q, Value, When
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
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
from apps.patients.models import Patient
from apps.pharmacy.forms import MedicalStoreRequestForm
from apps.pharmacy.models import MedicalStoreRequest
from apps.radiology.forms import (
    ImagingResultForm,
    RadiologyImageForm,
)
from apps.radiology.models import (
    ImagingRequest,
    ImagingResult,
    RadiologyComparison,
    RadiologyImage,
    RadiologyNotification,
    RadiologyQueue,
)
from apps.settingsapp.services import get_radiology_fee
from apps.visits.models import Visit
from apps.visits.services import transition_visit


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


def _is_imaging_request_payment_cleared(imaging_request):
    return InvoiceLineItem.objects.filter(
        source_model="radiology",
        source_id=imaging_request.pk,
        invoice__payment_status__in=["paid", "post_payment"],
        cashier_authorized=True,
    ).exists()


def _imaging_consumption_state(imaging_request):
    rows, total_cost = summarized_service_consumptions(
        imaging_request.branch,
        "radiology",
        imaging_request.pk,
    )
    return rows, total_cost, bool(rows)


def _can_correct_consumables(user):
    return user.is_superuser or user.role in {"system_admin", "director"}


def _default_requesting_department(user):
    role_map = {
        "doctor": "Consultation",
        "radiologist": "Radiology",
        "radiology_technician": "Radiology",
    }
    return role_map.get(getattr(user, "role", ""), "Clinical Department")


def _get_fixed_patient_and_visit(user, request):
    initial = {}
    patient_id = (request.GET.get("patient") or "").strip()
    visit_id = (request.GET.get("visit") or "").strip()

    fixed_patient = None
    fixed_visit = None

    try:
        if visit_id:
            fixed_visit = branch_queryset_for_user(
                user,
                Visit.objects.select_related("patient").filter(pk=int(visit_id)),
            ).first()
            if fixed_visit:
                fixed_patient = fixed_visit.patient
                initial["visit"] = fixed_visit.pk
                initial["patient"] = fixed_patient.pk

        if patient_id and not fixed_patient:
            fixed_patient = branch_queryset_for_user(
                user,
                Patient.objects.filter(pk=int(patient_id)),
            ).first()
            if fixed_patient:
                initial["patient"] = fixed_patient.pk
    except (TypeError, ValueError):
        fixed_patient = None
        fixed_visit = None
        initial = {}

    return fixed_patient, fixed_visit, initial


def _get_queue_entry(imaging_request):
    queue_entry, _ = RadiologyQueue.objects.get_or_create(
        imaging_request=imaging_request,
        defaults={
            "branch": imaging_request.branch,
            "status": imaging_request.status,
        },
    )
    return queue_entry


def _set_request_status(imaging_request, status, acting_user):
    imaging_request.status = status
    imaging_request.save(update_fields=["status", "updated_at"])

    queue_entry = _get_queue_entry(imaging_request)
    queue_entry.status = status
    queue_entry.assigned_staff = acting_user

    now = timezone.now()
    if status == "scheduled" and queue_entry.scheduled_for is None:
        queue_entry.scheduled_for = now
    if status == "patient_arrived" and queue_entry.patient_arrived_at is None:
        queue_entry.patient_arrived_at = now
    if status == "scanning" and queue_entry.scan_started_at is None:
        queue_entry.scan_started_at = now
    if status == "reporting" and queue_entry.reporting_started_at is None:
        queue_entry.reporting_started_at = now
    if status == "completed" and queue_entry.completed_at is None:
        queue_entry.completed_at = now
    queue_entry.save()

    if imaging_request.visit and status == "completed":
        transition_visit(imaging_request.visit, "waiting_doctor", acting_user)


def _notify_requesting_doctor(imaging_request, event_type):
    recipient = imaging_request.requested_by
    if not recipient:
        return

    event_labels = {
        "scan_completed": f"Radiology scan {imaging_request.request_identifier} has been completed.",
        "report_uploaded": f"Radiology report for {imaging_request.request_identifier} has been uploaded.",
    }
    RadiologyNotification.objects.create(
        branch=imaging_request.branch,
        imaging_request=imaging_request,
        recipient=recipient,
        event_type=event_type,
        message=event_labels.get(event_type, "Radiology update available."),
    )

    ImagingResult.objects.filter(imaging_request=imaging_request).update(
        notified_requesting_doctor_at=timezone.now()
    )


def _base_worklist_queryset(user):
    cleared_radiology_ids = InvoiceLineItem.objects.filter(
        source_model="radiology",
        invoice__payment_status__in=["paid", "post_payment"],
    ).values_list("source_id", flat=True)

    return branch_queryset_for_user(
        user,
        ImagingRequest.objects.select_related(
            "patient", "requested_by", "visit", "branch", "result"
        )
        .prefetch_related("images")
        .filter(pk__in=cleared_radiology_ids)
        .annotate(
            priority_rank=Case(
                When(priority="urgent", then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            status_rank=Case(
                When(status="requested", then=Value(0)),
                When(status="scheduled", then=Value(1)),
                When(status="patient_arrived", then=Value(2)),
                When(status="scanning", then=Value(3)),
                When(status="reporting", then=Value(4)),
                When(status="completed", then=Value(5)),
                default=Value(6),
                output_field=IntegerField(),
            ),
        )
        .order_by("priority_rank", "status_rank", "-date_requested"),
    )


def _dashboard_summary(queryset):
    return {
        "pending_requests": queryset.filter(
            status__in=["requested", "scheduled"]
        ).count(),
        "waiting_scan": queryset.filter(
            status__in=["requested", "scheduled", "patient_arrived"]
        ).count(),
        "waiting_report": queryset.filter(status__in=["scanning", "reporting"]).count(),
        "scans_in_progress": queryset.filter(
            status__in=["patient_arrived", "scanning", "reporting"]
        ).count(),
        "completed_scans": queryset.filter(status="completed").count(),
        "urgent_scans": queryset.filter(priority="urgent")
        .exclude(status="completed")
        .count(),
    }


def _notification_queryset(user):
    return branch_queryset_for_user(
        user,
        RadiologyNotification.objects.select_related(
            "imaging_request",
            "imaging_request__patient",
            "recipient",
        )
        .filter(recipient=user)
        .order_by("is_read", "-created_at"),
    )


def _search_worklist(queryset, search_query):
    if not search_query:
        return queryset
    return queryset.filter(
        Q(request_identifier__icontains=search_query)
        | Q(patient__patient_id__icontains=search_query)
        | Q(patient__first_name__icontains=search_query)
        | Q(patient__last_name__icontains=search_query)
        | Q(requested_department__icontains=search_query)
        | Q(specific_examination__icontains=search_query)
        | Q(requested_by__first_name__icontains=search_query)
        | Q(requested_by__last_name__icontains=search_query)
    )


def _unit_ui_config(imaging_type=None):
    if imaging_type == "xray":
        return {
            "unit_name": "X-Ray Unit",
            "capture_findings_label": "Capture X-Ray Findings",
            "capture_findings_short_label": "X-Ray Findings",
            "technician_role_label": "Radiographer / Technician",
            "technician_help_text": "The radiographer or technician confirms the scan was performed, records machine details, uploads images, and documents acquisition notes.",
            "radiologist_role_label": "Radiologist",
            "radiologist_help_text": "The radiologist interprets the X-ray, records findings and impression, then finalizes or notifies the requesting doctor.",
            "waiting_scan_label": "Waiting X-Ray Scan",
            "waiting_report_label": "Waiting X-Ray Report",
        }
    if imaging_type == "ultrasound":
        return {
            "unit_name": "Ultrasound Unit",
            "capture_findings_label": "Capture Ultrasound Findings",
            "capture_findings_short_label": "Ultrasound Findings",
            "technician_role_label": "Sonographer / Technician",
            "technician_help_text": "The sonographer or technician records the performed scan, machine used, uploaded images, and bedside acquisition notes.",
            "radiologist_role_label": "Radiologist / Reporting Clinician",
            "radiologist_help_text": "The radiologist or reporting clinician reviews the ultrasound study, enters findings and impression, then completes or notifies the requesting doctor.",
            "waiting_scan_label": "Waiting Ultrasound Scan",
            "waiting_report_label": "Waiting Ultrasound Report",
        }
    return {
        "unit_name": "Radiology",
        "capture_findings_label": "Capture Findings",
        "capture_findings_short_label": "Findings",
        "technician_role_label": "Technician",
        "technician_help_text": "The technician records performed scan details and uploads the study artifacts.",
        "radiologist_role_label": "Radiologist",
        "radiologist_help_text": "The radiologist interprets the study and finalizes the report.",
        "waiting_scan_label": "Waiting Scan",
        "waiting_report_label": "Waiting Report",
    }


def _render_dashboard(request, imaging_type=None, title="Radiology Dashboard"):
    queryset = _base_worklist_queryset(request.user)
    if imaging_type:
        queryset = queryset.filter(imaging_type=imaging_type)

    summary = _dashboard_summary(queryset)
    unit_config = _unit_ui_config(imaging_type)
    search_query = (request.GET.get("q") or "").strip()
    status_filter = (request.GET.get("status") or "").strip()

    filtered = _search_worklist(queryset, search_query)
    if status_filter:
        filtered = filtered.filter(status=status_filter)

    paginator = Paginator(filtered, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    recent_store_requests = branch_queryset_for_user(
        request.user,
        MedicalStoreRequest.objects.select_related("requested_by", "item")
        .filter(requested_for="radiology")
        .order_by("-created_at"),
    )
    if imaging_type in {"xray", "ultrasound"}:
        recent_store_requests = recent_store_requests.filter(
            requested_unit=imaging_type
        )
    recent_store_requests = recent_store_requests[:10]
    return render(
        request,
        "radiology/index.html",
        {
            "requests": page_obj.object_list,
            "page_obj": page_obj,
            "dashboard_title": title,
            "summary": summary,
            "search_query": search_query,
            "status_filter": status_filter,
            "status_choices": ImagingRequest.STATUS_CHOICES,
            "imaging_type_filter": imaging_type or "all",
            "unit_config": unit_config,
            "recent_store_requests": recent_store_requests,
        },
    )


def _render_stock_request_page(request, requested_unit=""):
    unit_label_map = {
        "xray": "X-Ray",
        "ultrasound": "Ultrasound",
    }
    requested_unit = (requested_unit or "").strip().lower()
    section_index_url = "radiology:index"
    section_label = "Radiology"
    page_title = "Request Radiology Stock From Medical Stores"
    submit_label = "Submit Radiology Request"
    success_message = "Radiology stock request submitted to medical stores."

    if requested_unit in unit_label_map:
        section_index_url = f"radiology:{requested_unit}"
        section_label = unit_label_map[requested_unit]
        page_title = (
            f"Request {unit_label_map[requested_unit]} Stock From Medical Stores"
        )
        submit_label = f"Submit {unit_label_map[requested_unit]} Request"
        success_message = f"{unit_label_map[requested_unit]} stock request submitted to medical stores."

    if request.method == "POST":
        form = MedicalStoreRequestForm(
            request.POST,
            user=request.user,
            requested_for="radiology",
            requested_unit=requested_unit,
        )
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                store_request = form.save(commit=False)
                store_request.branch = request.user.branch
                store_request.requested_by = request.user
                store_request.requested_for = "radiology"
                store_request.requested_unit = requested_unit
                item = form.cleaned_data["item"]
                store_request.item = item
                store_request.medicine_name = item.item_name
                store_request.category = item.category.name
                store_request.save()
                messages.success(request, success_message)
                return redirect(section_index_url)
    else:
        form = MedicalStoreRequestForm(
            user=request.user,
            requested_for="radiology",
            requested_unit=requested_unit,
        )

    return render(
        request,
        "pharmacy/medicine_form.html",
        {
            "form": form,
            "page_title": page_title,
            "submit_label": submit_label,
            "section_label": section_label,
            "section_index_url": section_index_url,
        },
    )


def _get_request_for_user_or_404(user, pk):
    imaging_request = (
        ImagingRequest.objects.select_related(
            "patient", "requested_by", "branch", "visit", "result"
        )
        .prefetch_related(
            Prefetch(
                "images", queryset=RadiologyImage.objects.order_by("-upload_date")
            ),
            Prefetch(
                "notifications",
                queryset=RadiologyNotification.objects.select_related(
                    "recipient"
                ).order_by("-created_at"),
            ),
        )
        .filter(pk=pk)
        .first()
    )
    if not imaging_request:
        raise Http404("Imaging request not found")

    scoped = branch_queryset_for_user(user, ImagingRequest.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Imaging request not found")
    return imaging_request


def _create_invoice_for_request(imaging_request, user):
    service_label = (
        imaging_request.examination_label or imaging_request.get_imaging_type_display()
    )
    service_amount = get_radiology_fee(
        imaging_request.imaging_type,
        imaging_request.specific_examination,
    )
    invoice = Invoice.objects.create(
        branch=imaging_request.branch,
        invoice_number=_generate_invoice_number(imaging_request.branch),
        patient=imaging_request.patient,
        visit=imaging_request.visit,
        services=f"Radiology - {service_label}",
        total_amount=service_amount,
        payment_method="cash",
        payment_status="pending",
        cashier=user,
    )
    InvoiceLineItem.objects.create(
        invoice=invoice,
        branch=invoice.branch,
        service_type="radiology",
        description=f"Radiology - {service_label}",
        amount=service_amount,
        unit_cost=Decimal("0.00"),
        total_cost=Decimal("0.00"),
        profit_amount=Decimal("0.00"),
        source_model="radiology",
        source_id=imaging_request.id,
    )
    return invoice


def _patient_snapshot(patient):
    if not patient:
        return None
    today = timezone.localdate()
    dob = patient.date_of_birth
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return {
        "patient_id": patient.patient_id,
        "full_name": f"{patient.first_name} {patient.last_name}",
        "age": age,
        "gender": patient.get_gender_display(),
    }


def _render_request_page(
    request,
    form_class,
    page_title,
    submit_label,
    imaging_type,
):
    fixed_patient, fixed_visit, initial = _get_fixed_patient_and_visit(
        request.user, request
    )
    initial.setdefault(
        "requested_department", _default_requesting_department(request.user)
    )
    lock_visit_patient = bool(fixed_visit or fixed_patient)

    if request.method == "POST":
        form = form_class(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                imaging_request = form.save(commit=False)
                imaging_request.branch = request.user.branch
                imaging_request.requested_by = request.user
                imaging_request.status = "requested"

                if fixed_visit:
                    imaging_request.visit = fixed_visit
                    imaging_request.patient = fixed_visit.patient
                elif fixed_patient:
                    imaging_request.patient = fixed_patient

                if not imaging_request.visit_id:
                    form.add_error(
                        "visit", "An active visit is required for radiology workflow."
                    )
                if not imaging_request.patient_id:
                    form.add_error("patient", "Patient is required.")
                elif (
                    imaging_request.visit_id
                    and imaging_request.patient_id != imaging_request.visit.patient_id
                ):
                    form.add_error(
                        "visit", "Selected visit does not belong to selected patient."
                    )

                if form.errors:
                    messages.error(
                        request, "Fix the highlighted request fields and try again."
                    )
                else:
                    imaging_request.imaging_type = imaging_type
                    imaging_request.clinical_notes = form.cleaned_data.get(
                        "clinical_notes", ""
                    )
                    imaging_request.save()
                    _get_queue_entry(imaging_request)

                    if imaging_request.visit:
                        transition_visit(
                            imaging_request.visit,
                            "billing_queue",
                            request.user,
                            notes="Radiology request created and forwarded to cashier for payment.",
                        )

                    invoice = _create_invoice_for_request(imaging_request, request.user)
                    submit_action = request.POST.get("submit_action", "send_queue")
                    if submit_action == "save_request":
                        messages.success(
                            request, "Radiology request saved successfully."
                        )
                        return redirect("radiology:detail", pk=imaging_request.pk)

                    messages.success(
                        request,
                        "Radiology request saved and sent to the radiology workflow queue after billing clearance.",
                    )
                    return redirect("radiology:detail", pk=imaging_request.pk)
    else:
        form = form_class(user=request.user, initial=initial)

    selected_patient = fixed_patient
    return render(
        request,
        "radiology/request_form.html",
        {
            "form": form,
            "page_title": page_title,
            "submit_label": submit_label,
            "lock_visit_patient": lock_visit_patient,
            "fixed_patient": fixed_patient,
            "fixed_visit": fixed_visit,
            "patient_snapshot": _patient_snapshot(selected_patient),
            "imaging_type": imaging_type,
        },
    )


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "view")
def index(request):
    return _render_dashboard(request)


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def result_feed_queue(request):
    if not request.GET.get("status"):
        query = request.GET.copy()
        query["status"] = "reporting"
        request.GET = query
    return _render_dashboard(request, title="Radiology Reporting Queue")


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "view")
def ultrasound(request):
    return _render_dashboard(
        request, imaging_type="ultrasound", title="Ultrasound Unit"
    )


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "view")
def xray(request):
    return _render_dashboard(request, imaging_type="xray", title="X-Ray Unit")


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def request_medical_store_stock(request):
    return _render_stock_request_page(request)


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def request_xray_stock(request):
    return _render_stock_request_page(request, requested_unit="xray")


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def request_ultrasound_stock(request):
    return _render_stock_request_page(request, requested_unit="ultrasound")


@login_required
@role_required(
    "radiology_technician", "radiologist", "doctor", "system_admin", "director"
)
@module_permission_required("radiology", "view")
def detail(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    return_to = _safe_return_url(request)
    payment_cleared = _is_imaging_request_payment_cleared(imaging_request)
    can_record_result = request.user.is_superuser or request.user.role in {
        "radiology_technician",
        "radiologist",
        "system_admin",
        "director",
    }
    if (
        request.user.role
        in {
            "radiology_technician",
            "radiologist",
        }
        and not payment_cleared
    ):
        raise Http404("Imaging request is awaiting cashier payment clearance.")

    previous_scans = branch_queryset_for_user(
        request.user,
        ImagingRequest.objects.select_related("result")
        .filter(patient=imaging_request.patient, status="completed")
        .exclude(pk=imaging_request.pk)
        .filter(body_region=imaging_request.body_region)
        .order_by("-date_requested"),
    )[:10]

    if request.user.role in {"doctor", "system_admin", "director"}:
        imaging_request.notifications.filter(
            recipient=request.user,
            is_read=False,
        ).update(is_read=True)

    consumption_rows, consumption_total_cost, consumables_recorded = (
        _imaging_consumption_state(imaging_request)
    )

    return render(
        request,
        "radiology/detail.html",
        {
            "imaging_request": imaging_request,
            "result": getattr(imaging_request, "result", None),
            "queue_entry": _get_queue_entry(imaging_request),
            "attachments": imaging_request.images.all(),
            "previous_scans": previous_scans,
            "latest_previous_scan": previous_scans[0] if previous_scans else None,
            "notifications": imaging_request.notifications.all(),
            "unit_config": _unit_ui_config(imaging_request.imaging_type),
            "payment_cleared": payment_cleared,
            "can_record_result": can_record_result,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
            "consumables_recorded": consumables_recorded,
            "can_correct_consumables": _can_correct_consumables(request.user),
            "return_to": return_to,
        },
    )


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def record_consumables(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    if not _is_imaging_request_payment_cleared(imaging_request):
        raise Http404("Imaging request is awaiting cashier payment clearance.")

    consumption_rows, consumption_total_cost, consumables_recorded = (
        _imaging_consumption_state(imaging_request)
    )
    if consumables_recorded:
        messages.info(
            request,
            "Consumables have already been recorded for this imaging request.",
        )
        return redirect("radiology:detail", pk=imaging_request.pk)

    if request.method == "POST":
        formset = build_service_consumable_formset(
            request.POST,
            branch=imaging_request.branch,
            store_department=imaging_request.imaging_type,
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
                    branch=imaging_request.branch,
                    service_type="radiology",
                    source_model="radiology",
                    source_id=imaging_request.pk,
                    selections=selections,
                    consumed_by=request.user,
                    store_department=imaging_request.imaging_type,
                    reference=(
                        f"Radiology request {imaging_request.request_identifier} consumables for "
                        f"{imaging_request.patient.first_name} {imaging_request.patient.last_name}"
                    ),
                )
            except ValidationError as exc:
                formset._non_form_errors = formset.error_class(exc.messages)
            else:
                messages.success(
                    request,
                    "Radiology consumables captured and departmental cost updated.",
                )
                return redirect("radiology:detail", pk=imaging_request.pk)
    else:
        formset = build_service_consumable_formset(
            branch=imaging_request.branch,
            store_department=imaging_request.imaging_type,
        )

    return render(
        request,
        "radiology/consumables_form.html",
        {
            "imaging_request": imaging_request,
            "formset": formset,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
            "unit_config": _unit_ui_config(imaging_request.imaging_type),
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("radiology", "update")
def correct_consumables(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    consumption_rows, consumption_total_cost, consumables_recorded = (
        _imaging_consumption_state(imaging_request)
    )
    if not consumables_recorded:
        messages.info(request, "There are no active consumables to correct.")
        return redirect("radiology:record_consumables", pk=imaging_request.pk)

    if request.method == "POST":
        form = ServiceConsumptionCorrectionForm(request.POST)
        if form.is_valid():
            reverse_service_consumptions(
                branch=imaging_request.branch,
                source_model="radiology",
                source_id=imaging_request.pk,
                reversed_by=request.user,
                reason=form.cleaned_data["reason"],
                reference=(
                    f"Radiology request {imaging_request.request_identifier} consumable correction"
                ),
            )
            messages.success(
                request,
                "Radiology consumables reversed. Re-enter the correct consumables now.",
            )
            return redirect("radiology:record_consumables", pk=imaging_request.pk)
    else:
        form = ServiceConsumptionCorrectionForm()

    return render(
        request,
        "radiology/consumables_correction_form.html",
        {
            "imaging_request": imaging_request,
            "form": form,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
            "unit_config": _unit_ui_config(imaging_request.imaging_type),
        },
    )


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("radiology", "view")
def notification_inbox(request):
    notifications = _notification_queryset(request.user)

    if request.method == "POST":
        notifications.filter(is_read=False).update(is_read=True)
        messages.success(request, "Radiology notifications marked as read.")
        return redirect("radiology:notification_inbox")

    filter_value = (request.GET.get("filter") or "unread").strip().lower()
    if filter_value == "all":
        filtered_notifications = notifications
    else:
        filter_value = "unread"
        filtered_notifications = notifications.filter(is_read=False)

    paginator = Paginator(filtered_notifications, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "radiology/notification_inbox.html",
        {
            "notifications": page_obj.object_list,
            "page_obj": page_obj,
            "filter_value": filter_value,
            "unread_count": notifications.filter(is_read=False).count(),
            "total_count": notifications.count(),
        },
    )


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("radiology", "view")
def mark_notification_read(request, notification_pk):
    if request.method != "POST":
        return redirect("radiology:notification_inbox")

    notification = (
        _notification_queryset(request.user).filter(pk=notification_pk).first()
    )
    if not notification:
        raise Http404("Radiology notification not found")

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    next_url = (request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("radiology:notification_inbox")


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def update_workflow(request, pk, action):
    if request.method != "POST":
        return redirect("radiology:detail", pk=pk)

    imaging_request = _get_request_for_user_or_404(request.user, pk)
    action_map = {
        "schedule": ("scheduled", "Scan scheduled."),
        "patient_arrived": ("patient_arrived", "Patient marked as arrived."),
        "start_scan": ("scanning", "Scan started."),
        "start_reporting": ("reporting", "Reporting started."),
        "mark_completed": ("completed", "Scan marked completed."),
    }
    if action not in action_map:
        raise Http404("Unknown radiology workflow action")

    if action in {
        "start_scan",
        "start_reporting",
        "mark_completed",
    } and not has_service_consumptions(
        imaging_request.branch,
        "radiology",
        imaging_request.pk,
    ):
        messages.warning(
            request,
            "Record apparatus and reagents used before starting or completing this scan.",
        )
        return redirect("radiology:record_consumables", pk=imaging_request.pk)

    status, message = action_map[action]
    _set_request_status(imaging_request, status, request.user)
    if status == "completed":
        _notify_requesting_doctor(imaging_request, "scan_completed")
    messages.success(request, message)
    next_url = (request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("radiology:detail", pk=pk)


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def upload_images(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    if not _is_imaging_request_payment_cleared(imaging_request):
        raise Http404("Imaging request is awaiting cashier payment clearance.")
    if not has_service_consumptions(
        imaging_request.branch,
        "radiology",
        imaging_request.pk,
    ):
        messages.warning(
            request,
            "Record apparatus and reagents used before uploading scan artifacts.",
        )
        return redirect("radiology:record_consumables", pk=imaging_request.pk)

    if request.method == "POST":
        form = RadiologyImageForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.branch = imaging_request.branch
            attachment.imaging_request = imaging_request
            attachment.uploaded_by = request.user
            attachment.save()
            if imaging_request.status in {"requested", "scheduled", "patient_arrived"}:
                _set_request_status(imaging_request, "scanning", request.user)
            messages.success(request, "Radiology attachment uploaded successfully.")
            return redirect("radiology:detail", pk=imaging_request.pk)
    else:
        form = RadiologyImageForm()

    return render(
        request,
        "radiology/image_form.html",
        {
            "form": form,
            "imaging_request": imaging_request,
            "page_title": "Upload Radiology Images",
        },
    )


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def upload_result(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    if not _is_imaging_request_payment_cleared(imaging_request):
        raise Http404("Imaging request is awaiting cashier payment clearance.")
    if not has_service_consumptions(
        imaging_request.branch,
        "radiology",
        imaging_request.pk,
    ):
        messages.warning(
            request,
            "Record apparatus and reagents used before documenting radiology findings.",
        )
        return redirect("radiology:record_consumables", pk=imaging_request.pk)

    result = ImagingResult.objects.filter(imaging_request=imaging_request).first()
    unit_config = _unit_ui_config(imaging_request.imaging_type)
    consumption_rows, consumption_total_cost, _ = _imaging_consumption_state(
        imaging_request
    )

    if request.method == "POST":
        form = ImagingResultForm(
            request.POST,
            request.FILES,
            instance=result,
            user=request.user,
        )
        if form.is_valid():
            saved_result = form.save(commit=False)
            saved_result.imaging_request = imaging_request
            saved_result.branch = imaging_request.branch
            if (
                request.user.role == "radiology_technician"
                and not saved_result.technician
            ):
                saved_result.technician = request.user
            if request.user.role == "radiologist" and not saved_result.radiologist:
                saved_result.radiologist = request.user
            if not saved_result.examination:
                saved_result.examination = imaging_request.examination_label
            if not saved_result.clinical_information:
                saved_result.clinical_information = imaging_request.clinical_notes
            saved_result.save()

            action = request.POST.get("action", "save_report")
            if action == "mark_completed":
                _set_request_status(imaging_request, "completed", request.user)
                _notify_requesting_doctor(imaging_request, "scan_completed")
                _notify_requesting_doctor(imaging_request, "report_uploaded")
                messages.success(
                    request, "Radiology report saved and scan marked completed."
                )
            elif action == "notify_doctor":
                _set_request_status(imaging_request, "reporting", request.user)
                _notify_requesting_doctor(imaging_request, "report_uploaded")
                messages.success(
                    request, "Radiology report saved and requesting doctor notified."
                )
            else:
                _set_request_status(imaging_request, "reporting", request.user)
                messages.success(request, "Radiology report saved.")

            return redirect("radiology:detail", pk=imaging_request.pk)
    else:
        initial = {
            "examination": imaging_request.examination_label,
            "clinical_information": imaging_request.clinical_notes,
        }
        if request.user.role == "radiology_technician":
            initial["technician"] = request.user.pk
        elif request.user.role == "radiologist":
            initial["radiologist"] = request.user.pk
        form = ImagingResultForm(
            instance=result,
            user=request.user,
            initial=initial,
        )

    return render(
        request,
        "radiology/result_form.html",
        {
            "form": form,
            "imaging_request": imaging_request,
            "page_title": f"{unit_config['capture_findings_short_label']} Entry Form",
            "submit_label": unit_config["capture_findings_label"],
            "unit_config": unit_config,
            "consumption_rows": consumption_rows,
            "consumption_total_cost": consumption_total_cost,
        },
    )


@login_required
@role_required("radiology_technician", "radiologist", "system_admin", "director")
@module_permission_required("radiology", "update")
def notify_requesting_doctor(request, pk):
    if request.method != "POST":
        return redirect("radiology:detail", pk=pk)

    imaging_request = _get_request_for_user_or_404(request.user, pk)
    _notify_requesting_doctor(imaging_request, "report_uploaded")
    messages.success(request, "Requesting doctor notified.")
    return redirect("radiology:detail", pk=pk)


def _viewer_attachments(imaging_request):
    attachments = list(imaging_request.images.all())
    if getattr(imaging_request, "result", None):
        if imaging_request.result.image_file and not attachments:
            attachments.append(imaging_request.result)
    return attachments


@login_required
@role_required(
    "radiology_technician", "radiologist", "doctor", "system_admin", "director"
)
@module_permission_required("radiology", "view")
def viewer(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    return_to = _safe_return_url(request)
    attachments = _viewer_attachments(imaging_request)
    previous_scans = branch_queryset_for_user(
        request.user,
        ImagingRequest.objects.select_related("result")
        .prefetch_related("images")
        .filter(patient=imaging_request.patient, status="completed")
        .exclude(pk=imaging_request.pk)
        .filter(body_region=imaging_request.body_region)
        .order_by("-date_requested"),
    )[:10]

    return render(
        request,
        "radiology/viewer.html",
        {
            "imaging_request": imaging_request,
            "result": getattr(imaging_request, "result", None),
            "attachments": attachments,
            "previous_scans": previous_scans,
            "latest_previous_scan": previous_scans[0] if previous_scans else None,
            "return_to": return_to,
        },
    )


@login_required
@role_required(
    "radiology_technician", "radiologist", "doctor", "system_admin", "director"
)
@module_permission_required("radiology", "view")
def compare_with_previous(request, pk):
    imaging_request = _get_request_for_user_or_404(request.user, pk)
    return_to = _safe_return_url(request)
    previous_scan = branch_queryset_for_user(
        request.user,
        ImagingRequest.objects.select_related("result")
        .prefetch_related("images")
        .filter(patient=imaging_request.patient, status="completed")
        .exclude(pk=imaging_request.pk)
        .filter(body_region=imaging_request.body_region)
        .order_by("-date_requested"),
    ).first()
    if not previous_scan:
        messages.info(request, "No previous scan found for comparison.")
        return redirect("radiology:detail", pk=imaging_request.pk)

    RadiologyComparison.objects.get_or_create(
        branch=imaging_request.branch,
        current_request=imaging_request,
        previous_request=previous_scan,
        defaults={"compared_by": request.user},
    )

    return render(
        request,
        "radiology/compare.html",
        {
            "current_request": imaging_request,
            "previous_request": previous_scan,
            "current_attachments": _viewer_attachments(imaging_request),
            "previous_attachments": _viewer_attachments(previous_scan),
            "return_to": return_to,
        },
    )
