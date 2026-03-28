from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render

from apps.billing.models import InvoiceLineItem
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.referrals.forms import ReferralForm
from apps.referrals.models import Referral
from apps.visits.services import transition_visit


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("referrals", "view")
def index(request):
    cleared_referral_ids = InvoiceLineItem.objects.filter(
        source_model="referral",
        invoice__payment_status="paid",
    ).values_list("source_id", flat=True)
    queryset = branch_queryset_for_user(
        request.user,
        Referral.objects.select_related("patient", "referring_doctor")
        .filter(Q(visit__isnull=True) | Q(pk__in=cleared_referral_ids))
        .order_by("-referral_date"),
    )
    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "referrals/index.html",
        {"referrals": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
@role_required("doctor", "system_admin", "director")
@module_permission_required("referrals", "create")
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
        form = ReferralForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                referral = form.save(commit=False)
                referral.branch = request.user.branch
                referral.save()
                if referral.visit:
                    transition_visit(referral.visit, "billing_queue", request.user)
                return redirect("referrals:index")
    else:
        form = ReferralForm(user=request.user, initial=initial)

    return render(
        request,
        "referrals/form.html",
        {
            "form": form,
            "page_title": "New Referral",
            "submit_label": "Save Referral",
        },
    )
