from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from apps.admission.models import Admission
from apps.billing.models import Invoice
from apps.consultation.models import Consultation
from apps.consultation.forms import (
    ConsultationForm,
    ConsultationLabTestRequestForm,
    ConsultationPharmacyRequestForm,
    ConsultationRadiologyRequestForm,
    ConsultationReferralRequestForm,
    ConsultationTransferForm,
    build_pharmacy_formset,
)
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.laboratory.models import LabRequest
from apps.laboratory.forms import LAB_TEST_CHOICES
from apps.pharmacy.models import DispenseRecord, PharmacyRequest
from apps.pharmacy.services import (
    available_medicines_queryset,
    sync_branch_medicine_catalog,
)
from apps.radiology.models import ImagingRequest
from apps.referrals.models import Referral
from apps.triage.models import TriageRecord
from apps.visits.models import Visit
from apps.visits.services import transition_visit


def _normalize_panel(panel):
    value = (panel or "all").strip().lower()
    if value not in {"all", "active", "admitted", "archive"}:
        return "all"
    return value


def _selected_panel(request):
    return _normalize_panel(request.GET.get("panel") or request.POST.get("panel"))


def _redirect_consultation_index(panel):
    panel = _normalize_panel(panel)
    url = reverse("consultation:index")
    if panel != "all":
        url = f"{url}?panel={panel}"
    return redirect(url)


def _redirect_consultation_start(visit_id, panel):
    panel = _normalize_panel(panel)
    url = reverse("consultation:start", args=[visit_id])
    if panel != "all":
        url = f"{url}?panel={panel}"
    return redirect(url)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("consultation", "view")
def index(request):
    selected_panel = _selected_panel(request)

    doctor_active_filter = Q()
    if request.user.role == "doctor":
        doctor_active_filter = Q(status="admitted")

    waiting_queue = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient")
        .filter(status="waiting_doctor", check_out_time__isnull=True)
        .filter(Q(assigned_clinician__isnull=True) | Q(assigned_clinician=request.user))
        .order_by("check_in_time"),
    )[:30]

    active_cases = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient")
        .filter(check_out_time__isnull=True)
        .filter(
            Q(assigned_clinician=request.user)
            | Q(consultations__doctor=request.user)
            | Q(lab_requests__requested_by=request.user)
            | Q(imaging_requests__requested_by=request.user)
            | Q(referrals__referring_doctor=request.user)
            | Q(pharmacy_requests__requested_by=request.user)
            | doctor_active_filter
        )
        .distinct()
        .annotate(
            waiting_lab_results=Exists(
                LabRequest.objects.filter(
                    visit_id=OuterRef("pk"),
                    status__in=["requested", "processing"],
                )
            ),
            waiting_radiology_results=Exists(
                ImagingRequest.objects.filter(
                    visit_id=OuterRef("pk"),
                    status__in=[
                        "requested",
                        "scheduled",
                        "patient_arrived",
                        "scanning",
                        "reporting",
                    ],
                )
            ),
            waiting_pharmacy_results=Exists(
                PharmacyRequest.objects.filter(
                    visit_id=OuterRef("pk"),
                    status="requested",
                )
            ),
        )
        .order_by("-check_in_time"),
    )[:30]

    admitted_patients = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient")
        .filter(status="admitted", check_out_time__isnull=True)
        .order_by("-check_in_time"),
    )[:30]

    cleared_archive_qs = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient")
        .filter(
            check_out_time__isnull=False,
            events__to_status="completed",
            events__moved_by=request.user,
        )
        .distinct()
        .order_by("-check_out_time"),
    )
    archive_paginator = Paginator(cleared_archive_qs, 20)
    archive_page = request.GET.get("archive_page")
    cleared_archive = archive_paginator.get_page(archive_page)

    consultations = branch_queryset_for_user(
        request.user,
        Consultation.objects.select_related("patient", "doctor").order_by(
            "-created_at"
        ),
    )[:12]
    return render(
        request,
        "consultation/index.html",
        {
            "waiting_queue": waiting_queue,
            "active_cases": active_cases,
            "admitted_patients": admitted_patients,
            "cleared_archive": cleared_archive,
            "selected_panel": selected_panel,
            "consultations": consultations,
        },
    )


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("consultation", "create")
def start_next(request):
    selected_panel = _selected_panel(request)
    next_visit = branch_queryset_for_user(
        request.user,
        Visit.objects.filter(status="waiting_doctor", check_out_time__isnull=True)
        .filter(Q(assigned_clinician__isnull=True) | Q(assigned_clinician=request.user))
        .order_by("check_in_time"),
    ).first()
    if not next_visit:
        return _redirect_consultation_index(selected_panel)
    return _redirect_consultation_start(next_visit.pk, selected_panel)


def _get_visit_or_redirect_for_user(user, visit_id):
    visit = branch_queryset_for_user(
        user,
        Visit.objects.select_related("patient", "branch").filter(pk=visit_id),
    ).first()
    if not visit:
        return None
    if (
        user.role == "doctor"
        and visit.assigned_clinician_id
        and visit.assigned_clinician_id != user.id
        and visit.status != "admitted"
        and not user.can_view_all_branches
    ):
        return None
    return visit


def _assign_visit_to_clinician(visit, clinician, room=""):
    changed_fields = []
    if visit.assigned_clinician_id != clinician.id:
        visit.assigned_clinician = clinician
        changed_fields.append("assigned_clinician")
    if room and visit.assigned_consultation_room != room:
        visit.assigned_consultation_room = room
        changed_fields.append("assigned_consultation_room")
    if changed_fields:
        changed_fields.append("updated_at")
        visit.save(update_fields=changed_fields)


def _get_clinician_active_room(user):
    active_visit = (
        Visit.objects.filter(
            assigned_clinician=user,
            check_out_time__isnull=True,
        )
        .exclude(assigned_consultation_room="")
        .order_by("-updated_at")
        .first()
    )
    if not active_visit:
        return ""
    return active_visit.assigned_consultation_room


def _get_cashier_cycle_badge(visit):
    status_badges = {
        "billing_queue": ("Awaiting Cashier Clearance", "text-bg-warning"),
        "lab_requested": ("Cleared For Lab", "text-bg-info"),
        "radiology_requested": ("Cleared For Radiology", "text-bg-primary"),
    }
    return status_badges.get(visit.status)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def request_lab_test(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    _assign_visit_to_clinician(
        visit,
        request.user,
        room=visit.assigned_consultation_room,
    )

    form = ConsultationLabTestRequestForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Could not create lab request. Choose one test option and retry."
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    selected_test = (form.cleaned_data.get("test_type") or "").strip()
    external_test = (form.cleaned_data.get("external_test_name") or "").strip()
    comments = (form.cleaned_data.get("comments") or "").strip()

    test_name = selected_test or external_test
    if external_test:
        test_name = f"External: {external_test}"

    lab_request = LabRequest.objects.create(
        branch=visit.branch,
        patient=visit.patient,
        visit=visit,
        requested_by=request.user,
        test_type=test_name,
        status="requested",
        comments=comments,
    )

    transition_visit(
        visit,
        "billing_queue",
        request.user,
        notes="Doctor requested lab test; use Send To Cashier for billing invoice generation.",
    )

    messages.success(
        request,
        f"Lab request '{test_name}' created. Patient remains on your consultation workbench while waiting for results.",
    )
    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("consultation", "update")
def review_lab_result(request, visit_id, lab_request_id):
    selected_panel = _selected_panel(request)
    if request.method != "POST":
        return _redirect_consultation_start(visit_id, selected_panel)

    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit:
        return _redirect_consultation_index(selected_panel)

    lab_request = branch_queryset_for_user(
        request.user,
        LabRequest.objects.filter(pk=lab_request_id, visit=visit),
    ).first()
    if not lab_request:
        messages.error(request, "Lab request not found for this visit.")
        return _redirect_consultation_start(visit.pk, selected_panel)

    if lab_request.status == "completed":
        lab_request.status = "reviewed"
        lab_request.save(update_fields=["status", "updated_at"])
        messages.success(request, "Lab result reviewed from consultation room.")
    elif lab_request.status == "reviewed":
        messages.info(request, "Lab result is already reviewed.")
    else:
        messages.warning(
            request,
            "Lab result is not ready for review yet. Wait until laboratory marks it completed.",
        )

    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def request_radiology(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    _assign_visit_to_clinician(
        visit,
        request.user,
        room=visit.assigned_consultation_room,
    )

    form = ConsultationRadiologyRequestForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Could not create radiology request. Check fields and retry."
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    imaging_type = form.cleaned_data["imaging_type"]
    priority = form.cleaned_data["priority"]
    clinical_notes = (form.cleaned_data.get("clinical_notes") or "").strip()

    ImagingRequest.objects.create(
        branch=visit.branch,
        patient=visit.patient,
        visit=visit,
        requested_by=request.user,
        imaging_type=imaging_type,
        priority=priority,
        clinical_notes=clinical_notes,
        status="requested",
    )

    transition_visit(
        visit,
        "billing_queue",
        request.user,
        notes="Doctor requested radiology; use Send To Cashier for billing invoice generation.",
    )

    messages.success(
        request,
        "Radiology request submitted. Patient must clear payment at cashier before radiology processing.",
    )
    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def request_referral(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    _assign_visit_to_clinician(
        visit,
        request.user,
        room=visit.assigned_consultation_room,
    )

    form = ConsultationReferralRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Could not create referral. Check fields and retry.")
        return _redirect_consultation_start(visit_id, selected_panel)

    facility_name = form.cleaned_data["facility_name"]
    reason = form.cleaned_data["reason"]

    Referral.objects.create(
        branch=visit.branch,
        patient=visit.patient,
        visit=visit,
        referring_doctor=request.user,
        facility_name=facility_name,
        reason=reason,
    )

    transition_visit(
        visit,
        "billing_queue",
        request.user,
        notes="Doctor requested referral; use Send To Cashier for billing invoice generation.",
    )

    messages.success(
        request,
        "Referral request submitted. Patient must clear payment at cashier.",
    )
    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def request_pharmacy(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    _assign_visit_to_clinician(
        visit,
        request.user,
        room=visit.assigned_consultation_room,
    )

    formset = build_pharmacy_formset(request.user, data=request.POST)
    notes = (request.POST.get("notes") or "").strip()

    if not formset.is_valid():
        messages.error(
            request, "Could not create pharmacy request. Check fields and retry."
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    created = []
    for form in formset:
        if not form.cleaned_data or not form.cleaned_data.get("medicine"):
            continue
        medicine = form.cleaned_data["medicine"]
        quantity = form.cleaned_data["quantity"]
        PharmacyRequest.objects.create(
            branch=visit.branch,
            patient=visit.patient,
            visit=visit,
            requested_by=request.user,
            medicine=medicine,
            quantity=quantity,
            unit_price_snapshot=medicine.selling_price,
            notes=notes,
            status="requested",
        )
        created.append(f"{medicine.name} x{quantity}")

    if not created:
        messages.error(request, "Please select at least one medicine.")
        return _redirect_consultation_start(visit_id, selected_panel)

    transition_visit(
        visit,
        "billing_queue",
        request.user,
        notes="Doctor requested pharmacy items; send to cashier for billing clearance.",
    )
    summary = ", ".join(created)
    messages.success(
        request,
        f"Pharmacy request(s) submitted: {summary}. Patient remains on your consultation workbench while awaiting cashier clearance.",
    )
    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def send_to_cashier(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    transition_visit(
        visit,
        "billing_queue",
        request.user,
        notes="Doctor sent patient to cashier; invoice to be generated at billing desk.",
    )
    messages.success(
        request,
        "Patient sent to cashier. Cashier should now generate invoice from Billing module.",
    )
    return _redirect_consultation_start(visit.pk, selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def discharge_patient(request, visit_id):
    selected_panel = _selected_panel(request)
    if request.method != "POST":
        return _redirect_consultation_start(visit_id, selected_panel)

    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit:
        return _redirect_consultation_index(selected_panel)

    if visit.status != "admitted":
        messages.error(
            request,
            "Discharge is only applicable to admitted patients.",
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    if visit.check_out_time is not None or visit.status == "completed":
        messages.info(request, "This patient has already been discharged.")
        return _redirect_consultation_index(selected_panel)

    transition_visit(
        visit,
        "completed",
        request.user,
        notes="Patient discharged by doctor from consultation workbench.",
    )
    messages.success(request, "Patient discharged successfully.")
    return _redirect_consultation_index(selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def transfer_patient(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit or request.method != "POST":
        return _redirect_consultation_index(selected_panel)

    form = ConsultationTransferForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(
            request, "Could not transfer patient. Check clinician/room details."
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    new_clinician = form.cleaned_data["clinician"]
    new_room = form.cleaned_data["consultation_room"]
    reason = (form.cleaned_data.get("reason") or "").strip()

    active_room = _get_clinician_active_room(new_clinician)
    if active_room and active_room != new_room:
        messages.error(
            request,
            f"Selected clinician is currently assigned to {active_room}. Use that room to keep one clinician per room.",
        )
        return _redirect_consultation_start(visit_id, selected_panel)

    _assign_visit_to_clinician(visit, new_clinician, room=new_room)
    transition_visit(
        visit,
        "waiting_doctor",
        request.user,
        notes=f"Transferred to clinician {new_clinician.get_full_name() or new_clinician.username} in {new_room}. {reason}".strip(),
    )

    messages.success(
        request,
        f"Patient transferred to clinician {new_clinician.get_full_name() or new_clinician.username} ({new_room}).",
    )
    return _redirect_consultation_index(selected_panel)


@login_required
@role_required("doctor")
@module_permission_required("consultation", "create")
def complete_visit(request, visit_id):
    selected_panel = _selected_panel(request)
    if request.method != "POST":
        return _redirect_consultation_start(visit_id, selected_panel)

    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit:
        return _redirect_consultation_index(selected_panel)

    if visit.check_out_time is not None or visit.status == "completed":
        messages.info(request, "This visit is already completed.")
        return _redirect_consultation_index(selected_panel)

    transition_visit(
        visit,
        "completed",
        request.user,
        notes="Doctor marked the visit as completed from consultation workbench.",
    )
    messages.success(request, "Visit marked complete.")
    return _redirect_consultation_index(selected_panel)


@login_required
@role_required("doctor", "system_admin", "director")
def medicine_search_api(request):
    """Return matching medicines as JSON for autocomplete."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)

    user = request.user
    if getattr(user, "branch", None):
        sync_branch_medicine_catalog(user.branch)

    qs = (
        available_medicines_queryset().select_related("inventory_item").order_by("name")
    )
    if not user.can_view_all_branches:
        qs = qs.filter(branch_id=user.branch_id)

    qs = qs.filter(Q(name__icontains=q) | Q(category__icontains=q))[:20]

    results = []
    for med in qs:
        item = med.inventory_item
        strength = getattr(item, "strength", "") if item else ""
        dosage_form = (
            getattr(item, "get_dosage_form_display", lambda: "")() if item else ""
        )
        label = med.name
        if strength:
            label = f"{med.name} {strength}"
        if dosage_form:
            label = f"{label} ({dosage_form})"
        results.append(
            {
                "id": med.pk,
                "name": label,
                "category": med.category,
            }
        )
    return JsonResponse(results, safe=False)


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("consultation", "create")
def start(request, visit_id):
    selected_panel = _selected_panel(request)
    visit = _get_visit_or_redirect_for_user(request.user, visit_id)
    if not visit:
        messages.error(request, "This patient is assigned to another clinician.")
        return _redirect_consultation_index(selected_panel)

    if request.user.role == "doctor" and not visit.assigned_clinician_id:
        default_room = _get_clinician_active_room(request.user) or "Consultation Room 1"
        _assign_visit_to_clinician(visit, request.user, room=default_room)

    latest_triage = branch_queryset_for_user(
        request.user,
        TriageRecord.objects.filter(visit=visit).order_by("-date"),
    ).first()

    if request.method == "POST":
        form = ConsultationForm(request.POST)
        if form.is_valid():
            requested_room = form.cleaned_data["consultation_room"]
            active_room = _get_clinician_active_room(request.user)
            if active_room and active_room != requested_room:
                form.add_error(
                    "consultation_room",
                    f"You are currently assigned to {active_room}. Keep one clinician in one room.",
                )
                return render(
                    request,
                    "consultation/form.html",
                    {
                        "visit": visit,
                        "patient": visit.patient,
                        "form": form,
                        "lab_test_form": ConsultationLabTestRequestForm(),
                        "pharmacy_request_form": ConsultationPharmacyRequestForm(
                            user=request.user
                        ),
                        "pharmacy_formset": build_pharmacy_formset(request.user),
                        "radiology_request_form": ConsultationRadiologyRequestForm(),
                        "referral_request_form": ConsultationReferralRequestForm(),
                        "transfer_form": ConsultationTransferForm(user=request.user),
                        "cashier_cycle_badge": _get_cashier_cycle_badge(visit),
                        "selected_panel": selected_panel,
                        "available_lab_tests": [
                            label for value, label in LAB_TEST_CHOICES if value
                        ],
                        "triage_records": branch_queryset_for_user(
                            request.user,
                            TriageRecord.objects.filter(visit=visit).order_by("-date"),
                        )[:10],
                        "current_visit_lab_results": branch_queryset_for_user(
                            request.user,
                            LabRequest.objects.filter(
                                visit=visit,
                                status__in=["completed", "reviewed"],
                            ).order_by("-date"),
                        )[:10],
                        "pending_visit_lab_requests": branch_queryset_for_user(
                            request.user,
                            LabRequest.objects.filter(
                                visit=visit,
                                status__in=["requested", "processing"],
                            ).order_by("-date"),
                        )[:10],
                        "patient_lab_history": branch_queryset_for_user(
                            request.user,
                            LabRequest.objects.select_related("visit")
                            .filter(patient=visit.patient)
                            .filter(status__in=["completed", "reviewed"])
                            .exclude(visit=visit)
                            .order_by("-date"),
                        )[:30],
                        "current_visit_radiology_results": branch_queryset_for_user(
                            request.user,
                            ImagingRequest.objects.select_related("result")
                            .filter(visit=visit)
                            .order_by("-date_requested"),
                        )[:10],
                        "patient_radiology_history": branch_queryset_for_user(
                            request.user,
                            ImagingRequest.objects.select_related("result", "visit")
                            .filter(patient=visit.patient)
                            .exclude(visit=visit)
                            .order_by("-date_requested"),
                        )[:30],
                        "current_visit_pharmacy_records": branch_queryset_for_user(
                            request.user,
                            DispenseRecord.objects.select_related(
                                "medicine", "dispensed_by"
                            )
                            .filter(visit=visit)
                            .order_by("-dispensed_at"),
                        )[:10],
                        "current_visit_pharmacy_requests": branch_queryset_for_user(
                            request.user,
                            PharmacyRequest.objects.select_related(
                                "medicine", "requested_by"
                            )
                            .filter(visit=visit)
                            .order_by("-date_requested"),
                        )[:10],
                        "patient_pharmacy_history": branch_queryset_for_user(
                            request.user,
                            DispenseRecord.objects.select_related(
                                "medicine", "dispensed_by", "visit"
                            )
                            .filter(patient=visit.patient)
                            .exclude(visit=visit)
                            .order_by("-dispensed_at"),
                        )[:30],
                        "admissions": branch_queryset_for_user(
                            request.user,
                            Admission.objects.filter(visit=visit).order_by(
                                "-admission_date"
                            ),
                        )[:10],
                        "referrals": branch_queryset_for_user(
                            request.user,
                            Referral.objects.filter(visit=visit).order_by(
                                "-referral_date"
                            ),
                        )[:10],
                        "invoices": branch_queryset_for_user(
                            request.user,
                            Invoice.objects.filter(visit=visit).order_by("-created_at"),
                        )[:10],
                    },
                )

            consultation = form.save(commit=False)
            consultation.branch = visit.branch
            consultation.patient = visit.patient
            consultation.visit = visit
            consultation.doctor = request.user
            consultation.save()
            _assign_visit_to_clinician(
                visit,
                request.user,
                room=consultation.consultation_room,
            )

            if consultation.follow_up_date:
                messages.success(
                    request,
                    f"Consultation saved. Review date set for {consultation.follow_up_date}.",
                )
            return _redirect_consultation_index(selected_panel)
    else:
        form = ConsultationForm(
            initial={
                "symptoms": latest_triage.symptoms if latest_triage else "",
            }
        )

    context = {
        "visit": visit,
        "patient": visit.patient,
        "form": form,
        "lab_test_form": ConsultationLabTestRequestForm(),
        "pharmacy_request_form": ConsultationPharmacyRequestForm(user=request.user),
        "pharmacy_formset": build_pharmacy_formset(request.user),
        "radiology_request_form": ConsultationRadiologyRequestForm(),
        "referral_request_form": ConsultationReferralRequestForm(),
        "transfer_form": ConsultationTransferForm(user=request.user),
        "cashier_cycle_badge": _get_cashier_cycle_badge(visit),
        "selected_panel": selected_panel,
        "available_lab_tests": [label for value, label in LAB_TEST_CHOICES if value],
        "triage_records": branch_queryset_for_user(
            request.user,
            TriageRecord.objects.filter(visit=visit).order_by("-date"),
        )[:10],
        "current_visit_lab_results": branch_queryset_for_user(
            request.user,
            LabRequest.objects.filter(
                visit=visit,
                status__in=["completed", "reviewed"],
            ).order_by("-date"),
        )[:10],
        "pending_visit_lab_requests": branch_queryset_for_user(
            request.user,
            LabRequest.objects.filter(
                visit=visit,
                status__in=["requested", "processing"],
            ).order_by("-date"),
        )[:10],
        "patient_lab_history": branch_queryset_for_user(
            request.user,
            LabRequest.objects.select_related("visit")
            .filter(patient=visit.patient)
            .filter(status__in=["completed", "reviewed"])
            .exclude(visit=visit)
            .order_by("-date"),
        )[:30],
        "current_visit_radiology_results": branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:10],
        "patient_radiology_history": branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result", "visit")
            .filter(patient=visit.patient)
            .exclude(visit=visit)
            .order_by("-date_requested"),
        )[:30],
        "current_visit_pharmacy_records": branch_queryset_for_user(
            request.user,
            DispenseRecord.objects.select_related("medicine", "dispensed_by")
            .filter(visit=visit)
            .order_by("-dispensed_at"),
        )[:10],
        "current_visit_pharmacy_requests": branch_queryset_for_user(
            request.user,
            PharmacyRequest.objects.select_related("medicine", "requested_by")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:10],
        "patient_pharmacy_history": branch_queryset_for_user(
            request.user,
            DispenseRecord.objects.select_related("medicine", "dispensed_by", "visit")
            .filter(patient=visit.patient)
            .exclude(visit=visit)
            .order_by("-dispensed_at"),
        )[:30],
        "admissions": branch_queryset_for_user(
            request.user,
            Admission.objects.filter(visit=visit).order_by("-admission_date"),
        )[:10],
        "referrals": branch_queryset_for_user(
            request.user,
            Referral.objects.filter(visit=visit).order_by("-referral_date"),
        )[:10],
        "invoices": branch_queryset_for_user(
            request.user,
            Invoice.objects.filter(visit=visit).order_by("-created_at"),
        )[:10],
    }
    return render(request, "consultation/form.html", context)


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("consultation", "view")
def nurse_review(request, visit_id):
    """Read-only consultation workbench for nurses."""
    visit = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient", "branch").filter(pk=visit_id),
    ).first()
    if not visit:
        messages.error(request, "Visit not found or not accessible.")
        return redirect("consultation:index")

    latest_triage = branch_queryset_for_user(
        request.user,
        TriageRecord.objects.filter(visit=visit).order_by("-date"),
    ).first()

    consultations = branch_queryset_for_user(
        request.user,
        Consultation.objects.filter(visit=visit).order_by("-created_at"),
    )[:10]

    context = {
        "visit": visit,
        "patient": visit.patient,
        "consultations": consultations,
        "triage_records": branch_queryset_for_user(
            request.user,
            TriageRecord.objects.filter(visit=visit).order_by("-date"),
        )[:10],
        "current_visit_lab_results": branch_queryset_for_user(
            request.user,
            LabRequest.objects.filter(
                visit=visit,
                status__in=["completed", "reviewed"],
            ).order_by("-date"),
        )[:10],
        "pending_visit_lab_requests": branch_queryset_for_user(
            request.user,
            LabRequest.objects.filter(
                visit=visit,
                status__in=["requested", "processing"],
            ).order_by("-date"),
        )[:10],
        "patient_lab_history": branch_queryset_for_user(
            request.user,
            LabRequest.objects.select_related("visit")
            .filter(patient=visit.patient)
            .filter(status__in=["completed", "reviewed"])
            .exclude(visit=visit)
            .order_by("-date"),
        )[:30],
        "current_visit_radiology_results": branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:10],
        "patient_radiology_history": branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result", "visit")
            .filter(patient=visit.patient)
            .exclude(visit=visit)
            .order_by("-date_requested"),
        )[:30],
        "current_visit_pharmacy_records": branch_queryset_for_user(
            request.user,
            DispenseRecord.objects.select_related("medicine", "dispensed_by")
            .filter(visit=visit)
            .order_by("-dispensed_at"),
        )[:10],
        "current_visit_pharmacy_requests": branch_queryset_for_user(
            request.user,
            PharmacyRequest.objects.select_related("medicine", "requested_by")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:10],
        "patient_pharmacy_history": branch_queryset_for_user(
            request.user,
            DispenseRecord.objects.select_related("medicine", "dispensed_by", "visit")
            .filter(patient=visit.patient)
            .exclude(visit=visit)
            .order_by("-dispensed_at"),
        )[:30],
        "admissions": branch_queryset_for_user(
            request.user,
            Admission.objects.filter(visit=visit).order_by("-admission_date"),
        )[:10],
        "referrals": branch_queryset_for_user(
            request.user,
            Referral.objects.filter(visit=visit).order_by("-referral_date"),
        )[:10],
        "invoices": branch_queryset_for_user(
            request.user,
            Invoice.objects.filter(visit=visit).order_by("-created_at"),
        )[:10],
    }
    return render(request, "consultation/nurse_review.html", context)
