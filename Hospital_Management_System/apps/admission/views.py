from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.admission.forms import AdmissionForm, DischargeForm, NursingNoteForm, VitalSignForm
from apps.admission.models import Admission, Bed, NursingNote, VitalSign, Ward
from apps.consultation.models import Consultation
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.pharmacy.models import DispenseRecord, PharmacyRequest
from apps.radiology.models import ImagingRequest
from apps.triage.models import TriageRecord
from apps.visits.models import Visit
from apps.visits.services import transition_visit


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("admission", "view")
def index(request):
    queryset = branch_queryset_for_user(
        request.user,
        Admission.objects.select_related("patient", "doctor").order_by(
            "-admission_date"
        ),
    )

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__patient_id__icontains=query)
        )

    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "admission/index.html",
        {
            "admissions": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "status": status,
            "status_choices": (
                Admission.STATUS_CHOICES if hasattr(Admission, "STATUS_CHOICES") else []
            ),
        },
    )


def _get_admission_for_user_or_404(user, pk):
    admission = (
        Admission.objects.select_related("patient", "doctor", "branch")
        .filter(pk=pk)
        .first()
    )
    if not admission:
        raise Http404("Admission not found")

    scoped = branch_queryset_for_user(user, Admission.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Admission not found")
    return admission


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("admission", "create")
def create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    visit_id = request.GET.get("visit")
    try:
        if patient_id:
            initial["patient"] = int(patient_id)
        if visit_id:
            initial["visit"] = int(visit_id)
    except (TypeError, ValueError):
        initial = {}

    if request.method == "POST":
        form = AdmissionForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                admission = form.save(commit=False)
                admission.branch = request.user.branch
                admission.save()
                if admission.visit:
                    transition_visit(admission.visit, "admitted", request.user)
                return redirect("admission:detail", pk=admission.pk)
    else:
        form = AdmissionForm(user=request.user, initial=initial)

    # Build patient history if a patient is selected
    patient_history = None
    selected_patient_id = request.POST.get("patient") or request.GET.get("patient")
    if selected_patient_id:
        try:
            patient = Patient.objects.get(pk=int(selected_patient_id))
            patient_history = {
                "patient": patient,
                "visits": Visit.objects.filter(patient=patient).order_by(
                    "-check_in_time"
                )[:10],
                "admissions": Admission.objects.filter(patient=patient).order_by(
                    "-admission_date"
                )[:5],
                "triage_records": TriageRecord.objects.filter(patient=patient).order_by(
                    "-date"
                )[:5],
                "consultations": Consultation.objects.filter(patient=patient).order_by(
                    "-created_at"
                )[:5],
            }
        except (ValueError, Patient.DoesNotExist):
            pass

    return render(
        request,
        "admission/form.html",
        {
            "form": form,
            "page_title": "New Admission",
            "submit_label": "Save Admission",
            "patient_history": patient_history,
        },
    )


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("admission", "view")
def detail(request, pk):
    admission = _get_admission_for_user_or_404(request.user, pk)
    patient = admission.patient
    visit = admission.visit

    context = {"admission": admission}

    if visit:
        context["consultations"] = branch_queryset_for_user(
            request.user,
            Consultation.objects.filter(visit=visit).order_by("-created_at"),
        )[:10]
        context["triage_records"] = branch_queryset_for_user(
            request.user,
            TriageRecord.objects.filter(visit=visit).order_by("-date"),
        )[:10]
        context["lab_results"] = branch_queryset_for_user(
            request.user,
            LabRequest.objects.filter(visit=visit).order_by("-date"),
        )[:20]
        context["radiology_results"] = branch_queryset_for_user(
            request.user,
            ImagingRequest.objects.select_related("result")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:10]
        context["pharmacy_requests"] = branch_queryset_for_user(
            request.user,
            PharmacyRequest.objects.select_related("medicine")
            .filter(visit=visit)
            .order_by("-date_requested"),
        )[:20]
        context["pharmacy_dispensed"] = branch_queryset_for_user(
            request.user,
            DispenseRecord.objects.select_related("medicine")
            .filter(visit=visit)
            .order_by("-dispensed_at"),
        )[:20]

    context["nursing_notes"] = NursingNote.objects.filter(
        admission=admission
    ).select_related("nurse")[:10]

    context["vital_signs"] = VitalSign.objects.filter(
        admission=admission
    ).select_related("recorded_by").order_by("-created_at")[:10]

    context["vital_sign_form"] = VitalSignForm()

    return render(request, "admission/detail.html", context)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("admission", "update")
def discharge(request, pk):
    admission = _get_admission_for_user_or_404(request.user, pk)

    if request.method == "POST":
        form = DischargeForm(request.POST, instance=admission)
        if form.is_valid():
            discharge_obj = form.save(commit=False)
            if not discharge_obj.discharge_date:
                discharge_obj.discharge_date = timezone.now()
            discharge_obj.save()
            # Release the bed
            if discharge_obj.bed_assigned:
                Bed.objects.filter(pk=discharge_obj.bed_assigned_id).update(
                    status="available"
                )
            if discharge_obj.visit:
                transition_visit(discharge_obj.visit, "completed", request.user)
            return redirect("admission:detail", pk=admission.pk)
    else:
        initial = {}
        if admission.discharge_date is None:
            initial["discharge_date"] = timezone.now().strftime("%Y-%m-%dT%H:%M")
        form = DischargeForm(instance=admission, initial=initial)

    return render(
        request,
        "admission/discharge_form.html",
        {
            "form": form,
            "admission": admission,
            "page_title": "Discharge Patient",
            "submit_label": "Save Discharge",
        },
    )


# ── Nurse Station ─────────────────────────────────────────────


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def nurse_station(request):
    user = request.user
    active_admissions = branch_queryset_for_user(
        user,
        Admission.objects.select_related("patient", "doctor", "nurse")
        .filter(discharge_date__isnull=True)
        .order_by("-admission_date"),
    )

    my_patients = (
        active_admissions.filter(nurse=user)
        if user.role == "nurse"
        else active_admissions.none()
    )
    other_patients = (
        active_admissions.exclude(nurse=user)
        if user.role == "nurse"
        else active_admissions
    )

    recent_notes = branch_queryset_for_user(
        user,
        NursingNote.objects.select_related("nurse", "admission__patient")
        .filter(admission__discharge_date__isnull=True)
        .order_by("-created_at"),
    )[:20]

    return render(
        request,
        "admission/nurse_station.html",
        {
            "my_patients": my_patients,
            "other_patients": other_patients,
            "recent_notes": recent_notes,
            "vital_sign_form": VitalSignForm(),
            "note_form": NursingNoteForm(),
        },
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def add_nursing_note(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)

    if request.method == "POST":
        form = NursingNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.admission = admission
            note.nurse = request.user
            note.branch = request.user.branch
            note.save()
            return redirect("admission:detail", pk=admission.pk)
    else:
        form = NursingNoteForm()

    return render(
        request,
        "admission/nursing_note_form.html",
        {
            "form": form,
            "admission": admission,
            "page_title": "Add Nursing Note",
        },
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def nursing_notes(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    notes = branch_queryset_for_user(
        request.user,
        NursingNote.objects.filter(admission=admission)
        .select_related("nurse")
        .order_by("-created_at"),
    )
    return render(
        request,
        "admission/nursing_notes.html",
        {
            "admission": admission,
            "notes": notes,
        },
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "create")
def record_vitals(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = VitalSignForm(request.POST)
        if form.is_valid():
            vital = form.save(commit=False)
            vital.admission = admission
            vital.recorded_by = request.user
            vital.branch = admission.branch
            vital.save()
    return redirect("admission:detail", pk=admission.pk)


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def vitals_chart(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    vitals = admission.vital_signs.order_by("created_at")
    return render(
        request,
        "admission/vitals_chart.html",
        {
            "admission": admission,
            "vitals": vitals,
        },
    )


# ── Bed & Ward Management ────────────────────────────────────


@login_required
@role_required("system_admin", "director", "nurse", "doctor")
@module_permission_required("admission", "view")
def bed_management(request):
    wards = branch_queryset_for_user(
        request.user,
        Ward.objects.prefetch_related("beds").filter(is_active=True).order_by("name"),
    )
    return render(request, "admission/bed_management.html", {"wards": wards})
