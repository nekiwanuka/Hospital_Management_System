from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.admission.models import Admission
from apps.billing.models import ApprovalRequest, FinancialSequenceAnomaly, Invoice
from apps.branches.models import Branch
from apps.core.models import AuditLog
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.emergency.models import EmergencyCase
from apps.laboratory.models import LabRequest
from apps.pharmacy.models import DispenseRecord, Medicine
from apps.pharmacy.services import sync_branch_medicine_catalog
from apps.radiology.models import ImagingRequest
from apps.triage.models import TriageRecord


def home(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return redirect("accounts:login")


@login_required
def help_manuals(request):
    """Display department help manuals / user guides."""
    section = request.GET.get("section", "").strip()
    return render(request, "core/help.html", {"active_section": section})


def permission_denied_view(request, exception=None):
    """Custom 403 handler — renders the friendly template."""
    return render(request, "403.html", status=403)


def _role_specific_dashboard_redirect(user):
    if getattr(user, "role", "") != "radiology_technician":
        return None

    assigned_unit = (
        (getattr(user, "radiology_unit_assignment", "") or "").strip().lower()
    )
    if assigned_unit == "xray":
        return redirect("radiology:xray")
    if assigned_unit == "ultrasound":
        return redirect("radiology:ultrasound")
    return redirect("radiology:index")


@login_required
def dashboard(request):
    role_redirect = _role_specific_dashboard_redirect(request.user)
    if role_redirect is not None:
        return role_redirect

    exception_counts = {
        "pending_financial_approvals": 0,
        "open_sequence_anomalies": 0,
        "today_rollback_requests": 0,
    }
    if request.user.role in {"director", "system_admin"} or request.user.is_superuser:
        today = timezone.localdate()
        exception_counts["pending_financial_approvals"] = branch_queryset_for_user(
            request.user,
            ApprovalRequest.objects.filter(status="pending"),
        ).count()
        exception_counts["open_sequence_anomalies"] = branch_queryset_for_user(
            request.user,
            FinancialSequenceAnomaly.objects.filter(is_resolved=False),
        ).count()
        exception_counts["today_rollback_requests"] = branch_queryset_for_user(
            request.user,
            ApprovalRequest.objects.filter(
                approval_type="paid_rollback",
                created_at__date=today,
            ),
        ).count()

    context = {
        "is_director": request.user.role == "director" or request.user.is_superuser,
        "is_system_admin": request.user.role == "system_admin"
        or request.user.is_superuser,
        "exception_counts": exception_counts,
    }
    return render(request, "core/dashboard.html", context)


def _dashboard_metrics_for_user(user, branch_filter=None):
    today = timezone.localdate()
    month_start = today - timedelta(days=30)
    sale_amount_expr = ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    def _bq(qs):
        if branch_filter:
            return qs.filter(branch_id=branch_filter)
        return branch_queryset_for_user(user, qs)

    triage_qs = _bq(TriageRecord.objects.filter(date__date__range=(month_start, today)))
    emergency_qs = _bq(
        EmergencyCase.objects.filter(date__date__range=(month_start, today))
    )
    invoice_qs = _bq(Invoice.objects.filter(date__date__range=(month_start, today)))
    admission_qs = _bq(
        Admission.objects.filter(admission_date__date__range=(month_start, today)),
    )
    lab_qs = _bq(LabRequest.objects.filter(date__date__range=(month_start, today)))
    radiology_qs = _bq(
        ImagingRequest.objects.filter(date_requested__date__range=(month_start, today)),
    )
    pharmacy_qs = _bq(
        DispenseRecord.objects.filter(dispensed_at__date__range=(month_start, today)),
    )
    if branch_filter:
        try:
            b = Branch.objects.get(pk=branch_filter)
            sync_branch_medicine_catalog(b)
        except Branch.DoesNotExist:
            pass
        medicine_qs = Medicine.objects.filter(branch_id=branch_filter)
    else:
        if getattr(user, "branch", None):
            sync_branch_medicine_catalog(user.branch)
        medicine_qs = branch_queryset_for_user(user, Medicine.objects.all())

    return {
        "date_from": month_start,
        "date_to": today,
        "visits": triage_qs.count() + emergency_qs.count(),
        "revenue": invoice_qs.aggregate(
            total=Coalesce(Sum("total_amount"), Decimal("0.00"))
        )["total"],
        "lab_tests": lab_qs.count(),
        "radiology_scans": radiology_qs.count(),
        "pharmacy_sales": pharmacy_qs.aggregate(
            total=Coalesce(Sum(sale_amount_expr), Decimal("0.00"))
        )["total"],
        "admissions": admission_qs.count(),
        "active_admissions": _bq(
            Admission.objects.filter(discharge_date__isnull=True)
        ).count(),
        "low_stock_items": medicine_qs.filter(stock_quantity__lte=10).count(),
        "pending_lab": _bq(
            LabRequest.objects.filter(status__in=["requested", "processing"])
        ).count(),
        "pending_radiology": _bq(
            ImagingRequest.objects.filter(
                status__in=[
                    "requested",
                    "scheduled",
                    "patient_arrived",
                    "scanning",
                    "reporting",
                ]
            ),
        ).count(),
    }


def _branch_performance_for_user(user, branch_filter=None):
    today = timezone.localdate()
    month_start = today - timedelta(days=30)
    branches = Branch.objects.order_by("branch_name")
    if branch_filter:
        branches = branches.filter(id=branch_filter)
    elif not user.can_view_all_branches:
        branches = branches.filter(id=user.branch_id)

    return branches.annotate(
        visits=Count(
            "triagerecord",
            filter=Q(triagerecord__date__date__range=(month_start, today)),
            distinct=True,
        )
        + Count(
            "emergencycase",
            filter=Q(emergencycase__date__date__range=(month_start, today)),
            distinct=True,
        ),
        revenue=Coalesce(
            Sum(
                "invoice__total_amount",
                filter=Q(invoice__date__date__range=(month_start, today)),
            ),
            Decimal("0.00"),
        ),
        admissions=Count(
            "admission",
            filter=Q(admission__admission_date__date__range=(month_start, today)),
            distinct=True,
        ),
    ).values("branch_name", "visits", "revenue", "admissions")


@login_required
@role_required("director", "system_admin")
@module_permission_required("core", "view")
def director_dashboard(request):
    branch_filter = None
    selected_branch = None
    available_branches = Branch.objects.filter(status="active").order_by("branch_name")
    if not request.user.can_view_all_branches:
        available_branches = available_branches.filter(id=request.user.branch_id)

    branch_param = request.GET.get("branch", "")
    if branch_param and branch_param.isdigit():
        bid = int(branch_param)
        if available_branches.filter(id=bid).exists():
            branch_filter = bid
            selected_branch = available_branches.get(id=bid)

    audit_qs = AuditLog.objects.select_related("user", "branch").order_by("-created_at")
    if branch_filter:
        audit_qs = audit_qs.filter(branch_id=branch_filter)
    else:
        audit_qs = branch_queryset_for_user(request.user, audit_qs)

    context = {
        "metrics": _dashboard_metrics_for_user(request.user, branch_filter),
        "branch_rows": _branch_performance_for_user(request.user, branch_filter),
        "recent_audits": audit_qs[:50],
        "available_branches": available_branches,
        "selected_branch": selected_branch,
    }
    return render(request, "core/director_dashboard.html", context)


@login_required
@role_required("system_admin", "director")
@module_permission_required("core", "view")
def system_admin_dashboard(request):
    # Branch switching for admin/director
    branch_filter = None
    selected_branch = None
    available_branches = Branch.objects.filter(status="active").order_by("branch_name")
    if not request.user.can_view_all_branches:
        available_branches = available_branches.filter(id=request.user.branch_id)

    branch_param = request.GET.get("branch", "")
    if branch_param and branch_param.isdigit():
        bid = int(branch_param)
        if available_branches.filter(id=bid).exists():
            branch_filter = bid
            selected_branch = available_branches.get(id=bid)

    role_distribution = (
        User.objects.values("role").annotate(total=Count("id")).order_by("role")
    )
    audit_qs = AuditLog.objects.select_related("user", "branch").order_by("-created_at")
    if branch_filter:
        audit_qs = audit_qs.filter(branch_id=branch_filter)
    else:
        audit_qs = branch_queryset_for_user(request.user, audit_qs)
    recent_audits = audit_qs[:50]

    context = {
        "metrics": _dashboard_metrics_for_user(request.user, branch_filter),
        "branch_rows": _branch_performance_for_user(request.user, branch_filter),
        "role_distribution": role_distribution,
        "recent_audits": recent_audits,
        "available_branches": available_branches,
        "selected_branch": selected_branch,
    }
    return render(request, "core/system_admin_dashboard.html", context)


def setup_redirect(request):
    return redirect("settingsapp:install")


# ---------------------------------------------------------------------------
# Delete Request workflow
# ---------------------------------------------------------------------------


@login_required
def request_delete(request):
    """Any authenticated user can submit a delete request."""
    if request.method != "POST":
        raise PermissionDenied

    from apps.core.models import DeleteRequest

    object_type = request.POST.get("object_type", "").strip()
    object_id = request.POST.get("object_id", "").strip()
    object_label = request.POST.get("object_label", "").strip()
    reason = request.POST.get("reason", "").strip()
    redirect_url = request.POST.get("next", "/dashboard/")

    if not object_type or not object_id or not reason:
        messages.error(
            request, "Please provide all required fields for the delete request."
        )
        return redirect(redirect_url)

    DeleteRequest.objects.create(
        requested_by=request.user,
        branch=request.user.branch,
        object_type=object_type,
        object_id=int(object_id),
        object_label=object_label,
        reason=reason,
    )
    messages.success(request, "Delete request submitted. A director will review it.")
    return redirect(redirect_url)


@login_required
@role_required("director", "system_admin")
def delete_requests_list(request):
    """Director / system admin see pending and processed delete requests."""
    from apps.core.models import DeleteRequest

    qs = branch_queryset_for_user(
        request.user,
        DeleteRequest.objects.select_related("requested_by", "reviewed_by").order_by(
            "-created_at"
        ),
    )
    status_filter = request.GET.get("status", "pending")
    if status_filter in {"pending", "approved", "deleted", "rejected"}:
        qs = qs.filter(status=status_filter)
    else:
        status_filter = "all"

    return render(
        request,
        "core/delete_requests.html",
        {"delete_requests": qs[:100], "status_filter": status_filter},
    )


@login_required
@role_required("director", "system_admin")
def review_delete_request(request, pk):
    """Director soft-deletes, system admin permanently deletes."""
    from apps.core.models import DeleteRequest

    dr = get_object_or_404(DeleteRequest, pk=pk)
    scoped = branch_queryset_for_user(request.user, DeleteRequest.objects.filter(pk=pk))
    if not scoped.exists():
        raise PermissionDenied

    if request.method != "POST":
        return render(request, "core/review_delete_request.html", {"dr": dr})

    action = request.POST.get("action", "")
    notes = request.POST.get("reviewer_notes", "").strip()

    if action == "reject":
        dr.status = "rejected"
        dr.reviewed_by = request.user
        dr.reviewer_notes = notes
        dr.save(update_fields=["status", "reviewed_by", "reviewer_notes", "updated_at"])
        messages.info(request, "Delete request rejected.")

    elif action == "soft_delete":
        if (
            request.user.role not in ("director", "system_admin")
            and not request.user.is_superuser
        ):
            raise PermissionDenied
        dr.status = "approved"
        dr.reviewed_by = request.user
        dr.reviewer_notes = notes
        dr.save(update_fields=["status", "reviewed_by", "reviewer_notes", "updated_at"])
        messages.success(request, "Record soft-deleted (marked for permanent removal).")

    elif action == "hard_delete":
        if request.user.role != "system_admin" and not request.user.is_superuser:
            raise PermissionDenied("Only system admin can permanently delete.")
        dr.status = "deleted"
        dr.reviewed_by = request.user
        dr.reviewer_notes = notes
        dr.save(update_fields=["status", "reviewed_by", "reviewer_notes", "updated_at"])
        messages.success(request, "Record permanently deleted.")

    return redirect("core:delete_requests")
