from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.billing.models import Invoice
from apps.consultation.models import Consultation
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.settingsapp.services import get_consultation_fee
from apps.visits.services import transition_visit
from apps.visits.forms import VisitCreateForm
from apps.visits.models import Visit


@login_required
@role_required(
    "receptionist",
    "nurse",
    "doctor",
    "triage_officer",
    "lab_technician",
    "radiology_technician",
    "radiologist",
    "pharmacist",
    "cashier",
    "system_admin",
    "director",
)
@module_permission_required("visits", "view")
def index(request):
    queryset = branch_queryset_for_user(
        request.user,
        Visit.objects.select_related("patient", "created_by").order_by(
            "-check_in_time"
        ),
    )
    status = request.GET.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)

    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "visits/index.html",
        {
            "visits": page_obj.object_list,
            "page_obj": page_obj,
            "status": status,
            "status_choices": Visit.STATUS_CHOICES,
        },
    )


@login_required
@role_required("receptionist", "nurse", "system_admin", "director")
@module_permission_required("visits", "create")
def create(request):
    initial = {}
    patient_id = request.GET.get("patient")
    if patient_id:
        try:
            initial["patient"] = int(patient_id)
        except (TypeError, ValueError):
            initial = {}

    if request.method == "POST":
        form = VisitCreateForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                visit = form.save(commit=False)
                visit.branch = request.user.branch
                visit.created_by = request.user
                visit.status = "waiting_triage"
                visit.save()

                latest_follow_up = branch_queryset_for_user(
                    request.user,
                    Consultation.objects.filter(
                        patient=visit.patient,
                        follow_up_date__isnull=False,
                    ).order_by("-created_at"),
                ).first()

                if (
                    latest_follow_up
                    and latest_follow_up.follow_up_date
                    and latest_follow_up.follow_up_date >= timezone.localdate()
                ):
                    messages.info(
                        request,
                        f"Review visit is valid until {latest_follow_up.follow_up_date}. No cashier payment required.",
                    )
                    return redirect("visits:detail", pk=visit.pk)

                consultation_fee = get_consultation_fee()

                Invoice.objects.create(
                    branch=visit.branch,
                    invoice_number=f"INV-{timezone.now().strftime('%Y%m%d%H%M%S%f')}",
                    patient=visit.patient,
                    visit=visit,
                    services=f"Initial consultation registration - {consultation_fee}",
                    total_amount=consultation_fee,
                    payment_method="cash",
                    payment_status="pending",
                    cashier=request.user,
                )

                transition_visit(
                    visit,
                    "billing_queue",
                    request.user,
                    notes="Initial invoice initiated at visit registration.",
                )
                return redirect("visits:detail", pk=visit.pk)
    else:
        form = VisitCreateForm(user=request.user, initial=initial)

    return render(
        request,
        "visits/form.html",
        {
            "form": form,
            "page_title": "Register Visit",
            "submit_label": "Create Visit",
        },
    )


@login_required
@role_required(
    "receptionist",
    "nurse",
    "doctor",
    "triage_officer",
    "lab_technician",
    "radiology_technician",
    "radiologist",
    "pharmacist",
    "cashier",
    "system_admin",
    "director",
)
@module_permission_required("visits", "view")
def detail(request, pk):
    visit = (
        Visit.objects.select_related("patient", "branch", "created_by")
        .prefetch_related("events", "events__moved_by")
        .filter(pk=pk)
        .first()
    )
    if not visit:
        raise Http404("Visit not found")

    scoped = branch_queryset_for_user(request.user, Visit.objects.filter(pk=pk))
    if not scoped.exists():
        raise Http404("Visit not found")

    has_visit_invoice = branch_queryset_for_user(
        request.user,
        Invoice.objects.filter(visit=visit),
    ).exists()
    review_waiver = None
    if not has_visit_invoice:
        review_waiver = branch_queryset_for_user(
            request.user,
            Consultation.objects.filter(
                patient=visit.patient,
                follow_up_date__isnull=False,
                follow_up_date__gte=visit.check_in_time.date(),
                created_at__lte=visit.check_in_time,
            ).order_by("-follow_up_date", "-created_at"),
        ).first()

    return render(
        request,
        "visits/detail.html",
        {
            "visit": visit,
            "is_review_no_payment": bool(review_waiver),
            "review_valid_until": (
                review_waiver.follow_up_date if review_waiver else None
            ),
            "delete_object_type": "Visit",
            "delete_object_id": visit.pk,
            "delete_object_label": visit.visit_number,
            "delete_next_url": request.path,
        },
    )
