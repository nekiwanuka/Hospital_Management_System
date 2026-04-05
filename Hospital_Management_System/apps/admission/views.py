import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.admission.forms import (
    AdmissionForm,
    BedForm,
    CarryOutOrderForm,
    DailyReportForm,
    DischargeForm,
    DoctorOrderForm,
    IntakeOutputForm,
    MedicationAdministrationForm,
    NursingNoteForm,
    VitalSignForm,
    WardForm,
    WardRoundForm,
)
from apps.admission.models import (
    Admission,
    AdmissionDailyCharge,
    Bed,
    DailyReport,
    DoctorOrder,
    IntakeOutput,
    MedicationAdministration,
    NursingNote,
    VitalSign,
    Ward,
    WardRound,
)
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
from apps.settingsapp.services import get_ward_category_rate
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

    context["vital_signs"] = (
        VitalSign.objects.filter(admission=admission)
        .select_related("recorded_by")
        .order_by("-created_at")[:10]
    )

    context["vital_sign_form"] = VitalSignForm()

    # New nursing activities
    context["medication_records"] = (
        MedicationAdministration.objects.filter(admission=admission)
        .select_related("administered_by")
        .order_by("-scheduled_time")[:10]
    )
    context["ward_rounds"] = (
        WardRound.objects.filter(admission=admission)
        .select_related("doctor", "nurse")
        .order_by("-round_time")[:10]
    )
    context["active_orders"] = (
        DoctorOrder.objects.filter(admission=admission, status="active")
        .select_related("ordered_by")
        .order_by("-created_at")
    )
    context["daily_reports"] = (
        DailyReport.objects.filter(admission=admission)
        .select_related("nurse")
        .order_by("-report_date", "-created_at")[:5]
    )
    context["io_entries"] = (
        IntakeOutput.objects.filter(admission=admission)
        .select_related("recorded_by")
        .order_by("-recorded_at")[:10]
    )

    # Invoices for this patient (post-payment & pending) -- nurse visibility
    from apps.billing.models import Invoice

    admission_invoices = Invoice.objects.filter(
        branch=admission.branch,
        patient=admission.patient,
    )
    if admission.visit:
        admission_invoices = admission_invoices.filter(visit=admission.visit)
    admission_invoices = admission_invoices.order_by("-created_at")
    context["admission_invoices"] = admission_invoices
    context["total_invoiced"] = admission_invoices.aggregate(t=Sum("total_amount"))[
        "t"
    ] or Decimal("0.00")
    context["total_paid"] = admission_invoices.aggregate(t=Sum("amount_paid"))[
        "t"
    ] or Decimal("0.00")
    context["total_credit"] = context["total_invoiced"] - context["total_paid"]

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
        Admission.objects.select_related("patient", "doctor", "nurse", "ward_obj")
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

    # Build per-admission invoice summaries for nurse visibility
    from apps.billing.models import Invoice

    admission_invoice_map = {}
    for adm in active_admissions:
        inv_qs = Invoice.objects.filter(
            branch=adm.branch,
            patient=adm.patient,
        )
        if adm.visit:
            inv_qs = inv_qs.filter(visit=adm.visit)
        totals = inv_qs.aggregate(
            total_invoiced=Sum("total_amount"),
            total_paid=Sum("amount_paid"),
        )
        invoiced = totals["total_invoiced"] or Decimal("0.00")
        paid = totals["total_paid"] or Decimal("0.00")
        admission_invoice_map[adm.pk] = {
            "total_invoiced": invoiced,
            "total_paid": paid,
            "outstanding": invoiced - paid,
            "invoice_count": inv_qs.count(),
        }

    recent_notes = branch_queryset_for_user(
        user,
        NursingNote.objects.select_related("nurse", "admission__patient")
        .filter(admission__discharge_date__isnull=True)
        .order_by("-created_at"),
    )[:20]

    # Pending doctor orders for nurse action
    pending_orders = branch_queryset_for_user(
        user,
        DoctorOrder.objects.select_related("ordered_by", "admission__patient")
        .filter(admission__discharge_date__isnull=True, status="active")
        .order_by("-created_at"),
    )[:20]

    # Upcoming medication administrations
    upcoming_meds = branch_queryset_for_user(
        user,
        MedicationAdministration.objects.select_related(
            "administered_by", "admission__patient"
        )
        .filter(
            admission__discharge_date__isnull=True,
            status="given",
            administered_at__isnull=True,
        )
        .order_by("scheduled_time"),
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
            "admission_invoice_map": admission_invoice_map,
            "pending_orders": pending_orders,
            "upcoming_meds": upcoming_meds,
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


# ── Ward Setup Management ────────────────────────────────────


@login_required
@role_required("system_admin", "director")
@module_permission_required("admission", "create")
def ward_list(request):
    wards = branch_queryset_for_user(
        request.user,
        Ward.objects.prefetch_related("beds").order_by("name"),
    )
    return render(request, "admission/ward_list.html", {"wards": wards})


@login_required
@role_required("system_admin", "director")
@module_permission_required("admission", "create")
def ward_create(request):
    if request.method == "POST":
        form = WardForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Ward created successfully.")
            return redirect("admission:ward_list")
    else:
        form = WardForm(user=request.user)
    return render(
        request,
        "admission/ward_form.html",
        {"form": form, "page_title": "Create Ward", "submit_label": "Create Ward"},
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("admission", "update")
def ward_edit(request, pk):
    ward = get_object_or_404(
        branch_queryset_for_user(request.user, Ward.objects.all()), pk=pk
    )
    if request.method == "POST":
        form = WardForm(request.POST, instance=ward, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Ward updated.")
            return redirect("admission:ward_list")
    else:
        form = WardForm(instance=ward, user=request.user)
    return render(
        request,
        "admission/ward_form.html",
        {
            "form": form,
            "ward": ward,
            "page_title": "Edit Ward",
            "submit_label": "Save Changes",
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("admission", "create")
def bed_add(request):
    ward_id = request.GET.get("ward")
    initial = {}
    if ward_id:
        initial["ward"] = ward_id
    if request.method == "POST":
        form = BedForm(request.POST, user=request.user)
        if form.is_valid():
            bed = form.save(commit=False)
            bed.branch = form.cleaned_data["ward"].branch
            bed.save()
            messages.success(request, f"Bed {bed.bed_number} added.")
            return redirect("admission:ward_list")
    else:
        form = BedForm(user=request.user, initial=initial)
    return render(
        request,
        "admission/bed_form.html",
        {"form": form, "page_title": "Add Bed"},
    )


# ── Daily Ward Charges & Invoicing ───────────────────────────


def _generate_daily_charges(admission, up_to_date=None):
    """Create AdmissionDailyCharge rows for all un-billed days."""
    if not admission.ward_obj or admission.daily_rate <= 0:
        return []

    today = up_to_date or timezone.localdate()
    start = (
        admission.last_billed_date + datetime.timedelta(days=1)
        if admission.last_billed_date
        else admission.admission_date.date()
    )

    if admission.discharge_date:
        end = min(admission.discharge_date.date(), today)
    else:
        end = today

    new_charges = []
    current = start
    while current <= end:
        charge, created = AdmissionDailyCharge.objects.get_or_create(
            admission=admission,
            charge_date=current,
            defaults={
                "branch": admission.branch,
                "amount": admission.daily_rate,
                "ward_category": admission.ward_obj.ward_category,
            },
        )
        if created:
            new_charges.append(charge)
        current += datetime.timedelta(days=1)

    if new_charges:
        admission.last_billed_date = new_charges[-1].charge_date
        admission.save(update_fields=["last_billed_date", "updated_at"])

    return new_charges


@login_required
@role_required("nurse", "doctor", "system_admin", "director", "cashier")
@module_permission_required("admission", "view")
def daily_charges(request, pk):
    """View all daily charges for an admission, generate missing ones, and allow payment."""
    admission = _get_admission_for_user_or_404(request.user, pk)

    # Auto-generate any missing daily charges
    _generate_daily_charges(admission)

    charges = admission.daily_charges.order_by("-charge_date")
    total_charged = charges.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    total_billed = charges.filter(invoice_line__isnull=False).aggregate(
        t=Sum("amount")
    )["t"] or Decimal("0.00")
    total_unbilled = total_charged - total_billed

    return render(
        request,
        "admission/daily_charges.html",
        {
            "admission": admission,
            "charges": charges,
            "total_charged": total_charged,
            "total_billed": total_billed,
            "total_unbilled": total_unbilled,
        },
    )


@login_required
@role_required("nurse", "cashier", "system_admin", "director")
@module_permission_required("billing", "create")
def generate_daily_invoice(request, pk):
    """Bill the un-invoiced daily ward charges for an admission — attaches to existing invoice or creates new."""
    admission = _get_admission_for_user_or_404(request.user, pk)

    # Generate any missing daily charges first
    _generate_daily_charges(admission)

    unbilled = admission.daily_charges.filter(invoice_line__isnull=True).order_by(
        "charge_date"
    )
    if not unbilled.exists():
        messages.info(request, "No un-billed daily charges.")
        return redirect("admission:daily_charges", pk=pk)

    from apps.billing.models import Invoice, InvoiceLineItem

    with transaction.atomic():
        # Find or create an invoice for this patient/visit
        invoice = None
        if admission.visit:
            invoice = (
                Invoice.objects.filter(
                    branch=admission.branch,
                    patient=admission.patient,
                    visit=admission.visit,
                    payment_status__in=["pending", "partial", "post_payment"],
                )
                .order_by("-created_at")
                .first()
            )

        if not invoice:
            from apps.billing.views import _generate_invoice_number

            invoice = Invoice.objects.create(
                branch=admission.branch,
                invoice_number=_generate_invoice_number(admission.branch),
                patient=admission.patient,
                visit=admission.visit,
                services="Ward daily charges",
                total_amount=Decimal("0.00"),
                payment_method="cash",
                payment_status="post_payment" if admission.is_active else "pending",
                cashier=request.user,
            )

        total_new = Decimal("0.00")
        for charge in unbilled:
            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                branch=admission.branch,
                service_type="admission",
                description=f"Admission: Ward charge ({charge.get_ward_category_display()}) – {charge.charge_date:%d %b %Y}",
                amount=charge.amount,
                paid_amount=Decimal("0.00"),
                payment_status="pending",
                source_model="admission_daily_charge",
                source_id=charge.pk,
            )
            charge.invoice_line = line
            charge.save(update_fields=["invoice_line", "updated_at"])
            total_new += charge.amount

        invoice.total_amount = invoice.total_amount + total_new
        invoice.services = (invoice.services or "") + f"\nWard charges: {total_new}"
        invoice.save(update_fields=["total_amount", "services", "updated_at"])

    messages.success(
        request,
        f"Daily ward charges of {total_new:,.0f} added to invoice {invoice.invoice_number}.",
    )
    return redirect("admission:daily_charges", pk=pk)


@login_required
@role_required("nurse", "doctor", "cashier", "system_admin", "director")
@module_permission_required("admission", "view")
def print_daily_invoice(request, pk):
    """Print-ready view of daily charges for an admission."""
    admission = _get_admission_for_user_or_404(request.user, pk)
    _generate_daily_charges(admission)

    date_filter = request.GET.get("date", "")
    charges = admission.daily_charges.order_by("charge_date")
    if date_filter:
        try:
            filter_date = datetime.date.fromisoformat(date_filter)
            charges = charges.filter(charge_date=filter_date)
        except ValueError:
            pass

    total = charges.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    from apps.settingsapp.models import SystemSettings

    settings_obj = SystemSettings.objects.first()

    return render(
        request,
        "admission/print_daily_invoice.html",
        {
            "admission": admission,
            "charges": charges,
            "total": total,
            "date_filter": date_filter,
            "settings_obj": settings_obj,
        },
    )


# ── Medication Administration ────────────────────────────────


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "create")
def administer_medication(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = MedicationAdministrationForm(request.POST)
        if form.is_valid():
            med = form.save(commit=False)
            med.admission = admission
            med.administered_by = request.user
            med.branch = admission.branch
            if med.status == "given" and not med.administered_at:
                med.administered_at = timezone.now()
            med.save()
            messages.success(request, f"Medication '{med.medicine_name}' recorded.")
            return redirect("admission:detail", pk=admission.pk)
    else:
        form = MedicationAdministrationForm(
            initial={"scheduled_time": timezone.now().strftime("%Y-%m-%dT%H:%M")}
        )
    return render(
        request,
        "admission/medication_form.html",
        {"form": form, "admission": admission, "page_title": "Administer Medication"},
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def medication_chart(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    records = admission.medication_administrations.select_related(
        "administered_by"
    ).order_by("-scheduled_time")
    return render(
        request,
        "admission/medication_chart.html",
        {"admission": admission, "records": records},
    )


# ── Ward Rounds ──────────────────────────────────────────────


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("admission", "create")
def add_ward_round(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = WardRoundForm(request.POST)
        if form.is_valid():
            WardRound.objects.create(
                admission=admission,
                doctor=request.user,
                nurse=admission.nurse,
                branch=admission.branch,
                findings=form.cleaned_data["findings"],
                plan=form.cleaned_data["plan"],
            )
            messages.success(request, "Ward round recorded.")
            return redirect("admission:detail", pk=admission.pk)
    else:
        form = WardRoundForm()
    return render(
        request,
        "admission/ward_round_form.html",
        {"form": form, "admission": admission, "page_title": "Record Ward Round"},
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def ward_rounds_list(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    rounds = admission.ward_rounds.select_related("doctor", "nurse").order_by(
        "-round_time"
    )
    return render(
        request,
        "admission/ward_rounds.html",
        {"admission": admission, "rounds": rounds},
    )


# ── Doctor Orders ────────────────────────────────────────────


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("admission", "create")
def add_doctor_order(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = DoctorOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.admission = admission
            order.ordered_by = request.user
            order.branch = admission.branch
            order.save()
            messages.success(request, "Doctor order added.")
            return redirect("admission:detail", pk=admission.pk)
    else:
        form = DoctorOrderForm()
    return render(
        request,
        "admission/doctor_order_form.html",
        {"form": form, "admission": admission, "page_title": "New Doctor Order"},
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def doctor_orders_list(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    status_filter = request.GET.get("status", "active")
    orders = admission.doctor_orders.select_related("ordered_by", "carried_out_by")
    if status_filter in ("active", "carried_out", "cancelled"):
        orders = orders.filter(status=status_filter)
    return render(
        request,
        "admission/doctor_orders.html",
        {
            "admission": admission,
            "orders": orders,
            "status_filter": status_filter,
        },
    )


@login_required
@role_required("nurse", "system_admin", "director")
@module_permission_required("admission", "update")
def carry_out_order(request, admission_pk, order_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    order = get_object_or_404(DoctorOrder, pk=order_pk, admission=admission)
    if order.status != "active":
        messages.warning(request, "This order is no longer active.")
        return redirect("admission:doctor_orders", admission_pk=admission.pk)

    if request.method == "POST":
        form = CarryOutOrderForm(request.POST)
        if form.is_valid():
            order.status = "carried_out"
            order.carried_out_by = request.user
            order.carried_out_at = timezone.now()
            order.carried_out_notes = form.cleaned_data["notes"]
            order.save(
                update_fields=[
                    "status",
                    "carried_out_by",
                    "carried_out_at",
                    "carried_out_notes",
                    "updated_at",
                ]
            )
            messages.success(request, "Order marked as carried out.")
            return redirect("admission:doctor_orders", admission_pk=admission.pk)
    else:
        form = CarryOutOrderForm()
    return render(
        request,
        "admission/carry_out_order.html",
        {"form": form, "admission": admission, "order": order},
    )


# ── Daily Reports ────────────────────────────────────────────


@login_required
@role_required("nurse", "system_admin", "director")
@module_permission_required("admission", "create")
def add_daily_report(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = DailyReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.admission = admission
            report.nurse = request.user
            report.branch = admission.branch
            report.save()
            messages.success(request, "Daily report filed.")
            return redirect("admission:detail", pk=admission.pk)
    else:
        form = DailyReportForm(
            initial={"report_date": timezone.localdate().isoformat()}
        )
    return render(
        request,
        "admission/daily_report_form.html",
        {"form": form, "admission": admission, "page_title": "File Daily Report"},
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def daily_reports_list(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    reports = admission.daily_reports.select_related("nurse").order_by(
        "-report_date", "-created_at"
    )
    return render(
        request,
        "admission/daily_reports.html",
        {"admission": admission, "reports": reports},
    )


# ── Intake/Output Chart ─────────────────────────────────────


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "create")
def add_intake_output(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    if request.method == "POST":
        form = IntakeOutputForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.admission = admission
            entry.recorded_by = request.user
            entry.branch = admission.branch
            entry.save()
            messages.success(request, "I/O entry recorded.")
            return redirect("admission:intake_output", admission_pk=admission.pk)
    else:
        form = IntakeOutputForm(
            initial={"recorded_at": timezone.now().strftime("%Y-%m-%dT%H:%M")}
        )
    return render(
        request,
        "admission/intake_output_form.html",
        {"form": form, "admission": admission},
    )


@login_required
@role_required("nurse", "doctor", "system_admin", "director")
@module_permission_required("admission", "view")
def intake_output_chart(request, admission_pk):
    admission = _get_admission_for_user_or_404(request.user, admission_pk)
    entries = admission.intake_outputs.select_related("recorded_by").order_by(
        "-recorded_at"
    )
    total_intake = (
        entries.filter(entry_type__startswith="intake_").aggregate(t=Sum("amount_ml"))[
            "t"
        ]
        or 0
    )
    total_output = (
        entries.filter(entry_type__startswith="output_").aggregate(t=Sum("amount_ml"))[
            "t"
        ]
        or 0
    )
    return render(
        request,
        "admission/intake_output_chart.html",
        {
            "admission": admission,
            "entries": entries,
            "total_intake": total_intake,
            "total_output": total_output,
            "balance": total_intake - total_output,
            "io_form": IntakeOutputForm(
                initial={"recorded_at": timezone.now().strftime("%Y-%m-%dT%H:%M")}
            ),
        },
    )
