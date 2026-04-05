from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
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
    BabyRecordForm,
)
from apps.delivery.models import DeliveryRecord, DeliveryNote, BabyRecord


def _ensure_post_payment_invoice(record, user):
    """Find or create a post_payment invoice for an active delivery patient."""
    from apps.billing.models import Invoice
    from apps.billing.views import _generate_invoice_number

    inv = Invoice.objects.filter(
        branch=record.branch,
        patient=record.patient,
        payment_status__in=["pending", "partial", "post_payment"],
    )
    if record.visit:
        inv = inv.filter(visit=record.visit)
    existing = inv.order_by("-created_at").first()
    if existing:
        if existing.payment_status != "post_payment":
            existing.payment_status = "post_payment"
            existing.save(update_fields=["payment_status", "updated_at"])
        return existing

    return Invoice.objects.create(
        branch=record.branch,
        invoice_number=_generate_invoice_number(record.branch),
        patient=record.patient,
        visit=record.visit,
        services="Delivery / Post-delivery services",
        total_amount=Decimal("0.00"),
        payment_method="cash",
        payment_status="post_payment",
        cashier=user,
    )


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
    babies = record.babies.order_by("birth_order")
    note_form = DeliveryNoteForm()
    outcome_form = DeliveryOutcomeForm(instance=record)
    discharge_form = DeliveryDischargeForm(instance=record)
    baby_form = BabyRecordForm(initial={"birth_order": babies.count() + 1})

    # Invoice visibility for post-delivery observation
    from apps.billing.models import Invoice

    delivery_invoices = Invoice.objects.filter(
        branch=record.branch,
        patient=record.patient,
    )
    if record.visit:
        delivery_invoices = delivery_invoices.filter(visit=record.visit)
    delivery_invoices = delivery_invoices.order_by("-created_at")
    total_invoiced = delivery_invoices.aggregate(t=Sum("total_amount"))["t"] or Decimal(
        "0.00"
    )
    total_paid = delivery_invoices.aggregate(t=Sum("amount_paid"))["t"] or Decimal(
        "0.00"
    )

    return render(
        request,
        "delivery/detail.html",
        {
            "record": record,
            "notes": notes,
            "babies": babies,
            "note_form": note_form,
            "outcome_form": outcome_form,
            "discharge_form": discharge_form,
            "baby_form": baby_form,
            "delivery_invoices": delivery_invoices,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "total_credit": total_invoiced - total_paid,
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

        # Auto-create post_payment invoice when moving to post_delivery
        if new_status == "post_delivery":
            _ensure_post_payment_invoice(record, request.user)

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


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "create")
def add_baby(request, pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    if request.method == "POST":
        form = BabyRecordForm(request.POST)
        if form.is_valid():
            baby = form.save(commit=False)
            baby.delivery = record
            baby.branch = record.branch
            baby.save()
    return redirect("delivery:detail", pk=pk)


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "update")
def edit_baby(request, pk, baby_pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    baby = record.babies.filter(pk=baby_pk).first()
    if not baby:
        raise Http404("Baby record not found")

    if request.method == "POST":
        form = BabyRecordForm(request.POST, instance=baby)
        if form.is_valid():
            form.save()
            return redirect("delivery:detail", pk=pk)
    else:
        form = BabyRecordForm(instance=baby)

    return render(
        request,
        "delivery/form.html",
        {
            "form": form,
            "page_title": f"Edit Baby Record — Baby {baby.birth_order}",
            "submit_label": "Save Baby Record",
            "back_url": "delivery:detail",
            "back_pk": pk,
        },
    )


@login_required
@role_required("doctor", "nurse", "system_admin", "director")
@module_permission_required("delivery", "update")
def delete_baby(request, pk, baby_pk):
    record = _get_delivery_for_user_or_404(request.user, pk)
    baby = record.babies.filter(pk=baby_pk).first()
    if not baby:
        raise Http404("Baby record not found")
    if request.method == "POST":
        baby.delete()
    return redirect("delivery:detail", pk=pk)
