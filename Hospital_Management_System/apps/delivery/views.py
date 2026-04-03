from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.delivery.forms import (
    DeliveryRecordForm,
    DeliveryOutcomeForm,
    DeliveryDischargeForm,
    DeliveryNoteForm,
)
from apps.delivery.models import DeliveryRecord, DeliveryNote


def _get_delivery_for_user_or_404(user, pk):
    record = (
        DeliveryRecord.objects.select_related("patient", "delivered_by", "branch")
        .filter(pk=pk)
        .first()
    )
    if not record:
        raise Http404("Delivery record not found")
    scoped = branch_queryset_for_user(user, DeliveryRecord.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Delivery record not found")
    return record


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "view")
def index(request):
    queryset = branch_queryset_for_user(
        request.user,
        DeliveryRecord.objects.select_related("patient", "delivered_by").order_by(
            "-admitted_at"
        ),
    )

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(patient__first_name__icontains=query)
            | Q(patient__last_name__icontains=query)
            | Q(patient__patient_id__icontains=query)
        )

    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "delivery/index.html",
        {
            "deliveries": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "status_filter": status_filter,
            "status_choices": DeliveryRecord.STATUS_CHOICES,
        },
    )


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "create")
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
        form = DeliveryRecordForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                record = form.save(commit=False)
                record.branch = request.user.branch
                record.save()
                return redirect("delivery:detail", pk=record.pk)
    else:
        form = DeliveryRecordForm(user=request.user, initial=initial)

    return render(
        request,
        "delivery/form.html",
        {
            "form": form,
            "page_title": "New Delivery Admission",
            "submit_label": "Admit to Labour Ward",
        },
    )


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "view")
def detail(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    notes = record.delivery_notes.select_related("author").order_by("-created_at")
    note_form = DeliveryNoteForm()
    outcome_form = DeliveryOutcomeForm(instance=record)
    discharge_form = DeliveryDischargeForm(instance=record)
    return render(
        request,
        "delivery/detail.html",
        {
            "record": record,
            "notes": notes,
            "note_form": note_form,
            "outcome_form": outcome_form,
            "discharge_form": discharge_form,
        },
    )


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "update")
def record_outcome(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    if request.method == "POST":
        form = DeliveryOutcomeForm(request.POST, instance=record)
        if form.is_valid():
            record = form.save(commit=False)
            record.status = "delivered"
            if not record.delivery_datetime:
                record.delivery_datetime = timezone.now()
            record.save()
            return redirect("delivery:detail", pk=record.pk)
    return redirect("delivery:detail", pk=pk)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "update")
def update_status(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    new_status = request.POST.get("status", "").strip()
    valid_statuses = {s[0] for s in DeliveryRecord.STATUS_CHOICES}
    if request.method == "POST" and new_status in valid_statuses:
        record.status = new_status
        if new_status == "in_labour" and not record.labour_started_at:
            record.labour_started_at = timezone.now()
        record.save()
    return redirect("delivery:detail", pk=pk)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "update")
def discharge(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    if request.method == "POST":
        form = DeliveryDischargeForm(request.POST, instance=record)
        if form.is_valid():
            record = form.save(commit=False)
            record.status = "discharged"
            if not record.discharge_datetime:
                record.discharge_datetime = timezone.now()
            record.save()
            return redirect("delivery:detail", pk=record.pk)
    return redirect("delivery:detail", pk=pk)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "create")
def add_note(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    if request.method == "POST":
        form = DeliveryNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.delivery = record
            note.author = request.user
            note.branch = record.branch
            note.save()
    return redirect("delivery:detail", pk=pk)
