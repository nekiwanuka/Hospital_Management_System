from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.patients.models import PatientDocument
from apps.triage.forms import TriageEditForm, TriageRecordForm
from apps.triage.models import TriageRecord
from apps.triage.services import get_triage_eligible_visits
from apps.visits.services import transition_visit


@login_required
@role_required(
    "receptionist", "triage_officer", "nurse", "doctor", "system_admin", "director"
)
@module_permission_required("triage", "view")
def index(request):
    eligible_visits = get_triage_eligible_visits(request.user)
    queryset = branch_queryset_for_user(
        request.user,
        TriageRecord.objects.select_related("patient", "triage_officer").order_by(
            "-priority_score", "-date"
        ),
    )

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__patient_id__icontains=query)
            | Q(visit_number__icontains=query)
        )

    outcome = request.GET.get("outcome", "").strip()
    if outcome:
        queryset = queryset.filter(outcome=outcome)

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "triage/index.html",
        {
            "records": page_obj.object_list,
            "page_obj": page_obj,
            "eligible_visits": eligible_visits,
            "query": query,
            "outcome": outcome,
            "can_edit_triage": request.user.role
            in {
                "doctor",
                "triage_officer",
                "nurse",
                "system_admin",
                "director",
            },
        },
    )


@login_required
@role_required("receptionist", "triage_officer", "nurse", "system_admin", "director")
@module_permission_required("triage", "create")
def create(request):
    initial = {}
    visit_id = (request.GET.get("visit") or "").strip()
    if visit_id.isdigit():
        initial["visit"] = int(visit_id)

    if request.method == "POST":
        form = TriageRecordForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
                return render(
                    request,
                    "triage/form.html",
                    {
                        "form": form,
                        "page_title": "Record Triage",
                        "submit_label": "Save Triage Record",
                    },
                )

            record = form.save(commit=False)
            record.branch = request.user.branch
            record.triage_officer = request.user
            record.patient = record.visit.patient
            if record.visit and not record.visit_number:
                record.visit_number = record.visit.visit_number
            record.save()

            if record.visit:
                if record.outcome == "send_to_doctor":
                    transition_visit(record.visit, "waiting_doctor", request.user)
                elif record.outcome == "emergency":
                    transition_visit(record.visit, "radiology_requested", request.user)
                elif record.outcome == "admission":
                    transition_visit(record.visit, "admission_queue", request.user)

            return redirect("triage:index")
    else:
        form = TriageRecordForm(user=request.user, initial=initial)

    return render(
        request,
        "triage/form.html",
        {
            "form": form,
            "page_title": "Record Triage",
            "submit_label": "Save Triage Record",
        },
    )


def _get_triage_record_or_404(user, pk):
    from django.http import Http404

    record = (
        TriageRecord.objects.select_related("patient", "visit", "triage_officer")
        .filter(pk=pk)
        .first()
    )
    if not record:
        raise Http404("Triage record not found")
    scoped = branch_queryset_for_user(user, TriageRecord.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Triage record not found")
    return record


@login_required
@role_required("doctor", "triage_officer", "nurse", "system_admin", "director")
@module_permission_required("triage", "update")
def edit(request, pk):
    """Allow doctors/nurses to update medical data on a triage record.

    Patient and visit fields are NOT editable here.
    """
    record = _get_triage_record_or_404(request.user, pk)

    if request.method == "POST":
        form = TriageEditForm(request.POST, instance=record)
        if form.is_valid():
            form.save()  # save() triggers auto-priority recalc
            return redirect("triage:index")
    else:
        form = TriageEditForm(instance=record)

    return render(
        request,
        "triage/form.html",
        {
            "form": form,
            "record": record,
            "page_title": f"Edit Triage — {record.patient}",
            "submit_label": "Save Changes",
            "patient_documents": PatientDocument.objects.filter(
                patient=record.patient
            ).order_by("-created_at"),
        },
    )
