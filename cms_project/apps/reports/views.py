import csv
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.admission.models import Admission
from apps.billing.models import Invoice
from apps.billing.models import InvoiceLineItem
from apps.branches.models import Branch
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.emergency.models import EmergencyCase
from apps.inventory.models import Item
from apps.laboratory.models import LabRequest
from apps.pharmacy.models import DispenseRecord
from apps.radiology.models import ImagingRequest
from apps.reports.models import GeneratedReport
from apps.triage.models import TriageRecord
from apps.visits.models import Visit


REPORT_TYPES = {
    "daily_visits": "Daily Visits",
    "revenue": "Revenue",
    "financial_statement": "Financial Statement",
    "gross_profit": "Gross Profit",
    "laboratory_tests": "Laboratory Tests",
    "radiology_scans": "Radiology Scans",
    "pharmacy_sales": "Pharmacy Sales",
    "admissions": "Admissions",
    "branch_performance": "Branch Performance",
    "department_inventory": "Department Inventory",
}

GROSS_PROFIT_DEPARTMENT_LABELS = {
    "pharmacy": "Pharmacy",
    "laboratory": "Laboratory",
    "radiology": "Radiology",
    "consultation": "Consultation",
    "referral": "Referral",
}

GROSS_PROFIT_SERVICE_TYPES = {
    "pharmacy": ["pharmacy"],
    "laboratory": ["lab"],
    "radiology": ["radiology"],
    "consultation": ["consultation"],
    "referral": ["referral"],
}


def _report_branch_options(user):
    branch_options = Branch.objects.order_by("branch_name")
    if not user.can_view_all_branches:
        branch_options = branch_options.filter(pk=user.branch_id)
    return branch_options


def _parse_date(value):
    if not value:
        return None
    try:
        return timezone.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_range_from_request(request):
    today = timezone.localdate()
    default_start = today - timedelta(days=30)
    start = _parse_date(request.GET.get("date_from")) or default_start
    end = _parse_date(request.GET.get("date_to")) or today
    if start > end:
        start, end = end, start
    return start, end


def _build_daily_visits(user, start, end):
    triage_rows = branch_queryset_for_user(
        user,
        TriageRecord.objects.filter(date__date__range=(start, end))
        .annotate(day=TruncDate("date"))
        .values("day")
        .annotate(triage_count=Count("id"))
        .order_by("day"),
    )
    emergency_rows = branch_queryset_for_user(
        user,
        EmergencyCase.objects.filter(date__date__range=(start, end))
        .annotate(day=TruncDate("date"))
        .values("day")
        .annotate(emergency_count=Count("id"))
        .order_by("day"),
    )

    by_day = {}
    for row in triage_rows:
        by_day[row["day"]] = {
            "date": row["day"],
            "triage_visits": row["triage_count"],
            "emergency_visits": 0,
        }

    for row in emergency_rows:
        day = row["day"]
        if day not in by_day:
            by_day[day] = {
                "date": day,
                "triage_visits": 0,
                "emergency_visits": 0,
            }
        by_day[day]["emergency_visits"] = row["emergency_count"]

    rows = []
    for day in sorted(by_day.keys()):
        entry = by_day[day]
        entry["total_visits"] = entry["triage_visits"] + entry["emergency_visits"]
        rows.append(entry)

    return ["date", "triage_visits", "emergency_visits", "total_visits"], rows


def _build_revenue(user, start, end):
    rows = branch_queryset_for_user(
        user,
        Invoice.objects.filter(date__date__range=(start, end))
        .annotate(day=TruncDate("date"))
        .values("day")
        .annotate(
            invoice_count=Count("id"),
            amount=Coalesce(Sum("total_amount"), Decimal("0.00")),
        )
        .order_by("day"),
    )
    normalized = [
        {
            "date": row["day"],
            "invoice_count": row["invoice_count"],
            "amount": row["amount"],
        }
        for row in rows
    ]
    return ["date", "invoice_count", "amount"], normalized


def _build_financial_statement(user, start, end):
    invoices = branch_queryset_for_user(
        user, Invoice.objects.filter(date__date__range=(start, end))
    )
    sale_amount_expr = ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    pharmacy_sales = branch_queryset_for_user(
        user,
        DispenseRecord.objects.filter(dispensed_at__date__range=(start, end)),
    ).aggregate(total=Coalesce(Sum(sale_amount_expr), Decimal("0.00")))["total"]

    total_revenue = invoices.aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )["total"]
    total_paid = invoices.filter(payment_status="paid").aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )["total"]
    total_pending = invoices.filter(payment_status="pending").aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )["total"]
    total_partial = invoices.filter(payment_status="partial").aggregate(
        total=Coalesce(Sum("total_amount"), Decimal("0.00"))
    )["total"]

    rows = [
        {
            "metric": "Total Revenue",
            "amount": total_revenue,
        },
        {
            "metric": "Paid Revenue",
            "amount": total_paid,
        },
        {
            "metric": "Pending Receivables",
            "amount": total_pending,
        },
        {
            "metric": "Partial Receivables",
            "amount": total_partial,
        },
        {
            "metric": "Pharmacy Sales",
            "amount": pharmacy_sales,
        },
        {
            "metric": "Total Visits",
            "amount": branch_queryset_for_user(
                user, Visit.objects.filter(check_in_time__date__range=(start, end))
            ).count(),
        },
    ]
    return ["metric", "amount"], rows


def _build_gross_profit(user, start, end, branch_id=None, department=""):
    department_map = {
        "lab": "laboratory",
        "radiology": "radiology",
        "consultation": "consultation",
        "pharmacy": "pharmacy",
        "referral": "referral",
    }

    queryset = InvoiceLineItem.objects.select_related(
        "invoice", "invoice__branch"
    ).filter(invoice__date__date__range=(start, end))
    if branch_id:
        queryset = queryset.filter(invoice__branch_id=branch_id)

    department = (department or "").strip().lower()
    if department in GROSS_PROFIT_SERVICE_TYPES:
        queryset = queryset.filter(
            service_type__in=GROSS_PROFIT_SERVICE_TYPES[department]
        )

    rows = branch_queryset_for_user(
        user,
        queryset.annotate(day=TruncDate("invoice__date"))
        .values("day", "invoice__branch__branch_name", "service_type")
        .annotate(
            transactions=Count("id"),
            sales=Coalesce(Sum("amount"), Decimal("0.00")),
            cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
            profit=Coalesce(Sum("profit_amount"), Decimal("0.00")),
        )
        .order_by("day", "invoice__branch__branch_name", "service_type"),
    )

    normalized = [
        {
            "date": row["day"],
            "branch": row["invoice__branch__branch_name"],
            "department": department_map.get(row["service_type"], row["service_type"]),
            "service_type": row["service_type"],
            "transactions": row["transactions"],
            "sales": row["sales"],
            "cost": row["cost"],
            "profit": row["profit"],
        }
        for row in rows
    ]
    return [
        "date",
        "branch",
        "department",
        "service_type",
        "transactions",
        "sales",
        "cost",
        "profit",
    ], normalized


def _build_laboratory_profitability_detail(user, start, end, branch_id=None):
    line_items = branch_queryset_for_user(
        user,
        InvoiceLineItem.objects.select_related(
            "invoice",
            "invoice__branch",
            "invoice__patient",
        )
        .filter(
            source_model="lab",
            invoice__date__date__range=(start, end),
        )
        .order_by("-invoice__date", "-id"),
    )
    if branch_id:
        line_items = line_items.filter(invoice__branch_id=branch_id)

    request_map = {
        request.pk: request
        for request in branch_queryset_for_user(
            user,
            LabRequest.objects.select_related("patient", "branch").filter(
                pk__in=line_items.values_list("source_id", flat=True)
            ),
        )
    }

    rows = []
    for line_item in line_items:
        lab_request = request_map.get(line_item.source_id)
        patient = line_item.invoice.patient
        rows.append(
            {
                "date": timezone.localtime(line_item.invoice.date).date(),
                "branch": line_item.invoice.branch.branch_name,
                "patient": f"{patient.first_name} {patient.last_name}".strip(),
                "service": (
                    lab_request.test_type if lab_request else line_item.description
                ),
                "status": (lab_request.get_status_display() if lab_request else "-"),
                "invoice_number": line_item.invoice.invoice_number,
                "fee": line_item.amount,
                "cost": line_item.total_cost,
                "profit": line_item.profit_amount,
                "detail_url": (
                    reverse("laboratory:detail", args=[lab_request.pk])
                    if lab_request
                    else ""
                ),
            }
        )

    totals = line_items.aggregate(
        total_fee=Coalesce(Sum("amount"), Decimal("0.00")),
        total_cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
        total_profit=Coalesce(Sum("profit_amount"), Decimal("0.00")),
    )
    return rows, totals


def _build_radiology_profitability_detail(user, start, end, branch_id=None):
    line_items = branch_queryset_for_user(
        user,
        InvoiceLineItem.objects.select_related(
            "invoice",
            "invoice__branch",
            "invoice__patient",
        )
        .filter(
            source_model="radiology",
            invoice__date__date__range=(start, end),
        )
        .order_by("-invoice__date", "-id"),
    )
    if branch_id:
        line_items = line_items.filter(invoice__branch_id=branch_id)

    request_map = {
        request.pk: request
        for request in branch_queryset_for_user(
            user,
            ImagingRequest.objects.select_related("patient", "branch").filter(
                pk__in=line_items.values_list("source_id", flat=True)
            ),
        )
    }

    rows = []
    for line_item in line_items:
        imaging_request = request_map.get(line_item.source_id)
        patient = line_item.invoice.patient
        rows.append(
            {
                "date": timezone.localtime(line_item.invoice.date).date(),
                "branch": line_item.invoice.branch.branch_name,
                "patient": f"{patient.first_name} {patient.last_name}".strip(),
                "unit": (
                    imaging_request.get_imaging_type_display()
                    if imaging_request
                    else "Radiology"
                ),
                "service": (
                    imaging_request.examination_label
                    if imaging_request and imaging_request.examination_label
                    else line_item.description
                ),
                "status": (
                    imaging_request.get_status_display() if imaging_request else "-"
                ),
                "invoice_number": line_item.invoice.invoice_number,
                "fee": line_item.amount,
                "cost": line_item.total_cost,
                "profit": line_item.profit_amount,
                "detail_url": (
                    reverse("radiology:detail", args=[imaging_request.pk])
                    if imaging_request
                    else ""
                ),
            }
        )

    totals = line_items.aggregate(
        total_fee=Coalesce(Sum("amount"), Decimal("0.00")),
        total_cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
        total_profit=Coalesce(Sum("profit_amount"), Decimal("0.00")),
    )
    return rows, totals


def _build_laboratory_tests(user, start, end):
    rows = branch_queryset_for_user(
        user,
        LabRequest.objects.filter(date__date__range=(start, end))
        .values("test_type", "status")
        .annotate(total=Count("id"))
        .order_by("test_type", "status"),
    )
    return ["test_type", "status", "total"], list(rows)


def _build_radiology_scans(user, start, end):
    type_map = dict(ImagingRequest.IMAGING_TYPE_CHOICES)
    rows = branch_queryset_for_user(
        user,
        ImagingRequest.objects.filter(date_requested__date__range=(start, end))
        .values("imaging_type", "status")
        .annotate(total=Count("id"))
        .order_by("imaging_type", "status"),
    )
    normalized = [
        {
            "imaging_type": type_map.get(row["imaging_type"], row["imaging_type"]),
            "status": row["status"],
            "total": row["total"],
        }
        for row in rows
    ]
    return ["imaging_type", "status", "total"], normalized


def _build_pharmacy_sales(user, start, end):
    sale_amount_expr = ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = branch_queryset_for_user(
        user,
        DispenseRecord.objects.filter(dispensed_at__date__range=(start, end))
        .values("medicine__name")
        .annotate(
            units_sold=Coalesce(Sum("quantity"), 0),
            amount=Coalesce(Sum(sale_amount_expr), Decimal("0.00")),
        )
        .order_by("medicine__name"),
    )
    normalized = [
        {
            "medicine": row["medicine__name"],
            "units_sold": row["units_sold"],
            "amount": row["amount"],
        }
        for row in rows
    ]
    return ["medicine", "units_sold", "amount"], normalized


def _build_admissions(user, start, end):
    rows = branch_queryset_for_user(
        user,
        Admission.objects.filter(admission_date__date__range=(start, end))
        .annotate(day=TruncDate("admission_date"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day"),
    )
    normalized = [{"date": row["day"], "total": row["total"]} for row in rows]
    return ["date", "total"], normalized


def _build_branch_performance(user, start, end):
    sale_amount_expr = ExpressionWrapper(
        F("dispenserecord__quantity") * F("dispenserecord__unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    branches = Branch.objects.order_by("branch_name")
    if not user.can_view_all_branches:
        branches = branches.filter(id=user.branch_id)

    rows = branches.annotate(
        visits=Count(
            "triagerecord",
            filter=Q(triagerecord__date__date__range=(start, end)),
            distinct=True,
        ),
        revenue=Coalesce(
            Sum(
                "invoice__total_amount",
                filter=Q(invoice__date__date__range=(start, end)),
            ),
            Decimal("0.00"),
        ),
        lab_tests=Count(
            "labrequest",
            filter=Q(labrequest__date__date__range=(start, end)),
            distinct=True,
        ),
        radiology_scans=Count(
            "imagingrequest",
            filter=Q(imagingrequest__date_requested__date__range=(start, end)),
            distinct=True,
        ),
        pharmacy_sales=Coalesce(
            Sum(
                sale_amount_expr,
                filter=Q(dispenserecord__dispensed_at__date__range=(start, end)),
            ),
            Decimal("0.00"),
        ),
        admissions=Count(
            "admission",
            filter=Q(admission__admission_date__date__range=(start, end)),
            distinct=True,
        ),
    ).values(
        "branch_name",
        "visits",
        "revenue",
        "lab_tests",
        "radiology_scans",
        "pharmacy_sales",
        "admissions",
    )

    normalized = []
    for row in rows:
        visits = row["visits"] or 0
        revenue = row["revenue"] or Decimal("0.00")
        row["revenue_per_visit"] = (revenue / visits) if visits else Decimal("0.00")
        normalized.append(row)

    return [
        "branch_name",
        "visits",
        "revenue",
        "lab_tests",
        "radiology_scans",
        "pharmacy_sales",
        "admissions",
        "revenue_per_visit",
    ], normalized


def _build_department_inventory(user, start, end):
    del start, end

    items = branch_queryset_for_user(
        user,
        Item.objects.filter(is_active=True).annotate(
            total_quantity=Coalesce(Sum("batches__quantity_remaining"), 0),
            stock_value=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F("batches__quantity_remaining") * F("batches__unit_cost"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                ),
                Decimal("0.00"),
            ),
        ),
    )

    rows = {}
    for item in items:
        department = item.mapped_department
        entry = rows.setdefault(
            department,
            {
                "department": department,
                "item_count": 0,
                "quantity": 0,
                "stock_value": Decimal("0.00"),
            },
        )
        entry["item_count"] += 1
        entry["quantity"] += item.total_quantity or 0
        entry["stock_value"] += item.stock_value or Decimal("0.00")

    normalized = list(rows.values())
    normalized.sort(key=lambda row: row["department"])
    return ["department", "item_count", "quantity", "stock_value"], normalized


REPORT_BUILDERS = {
    "daily_visits": _build_daily_visits,
    "revenue": _build_revenue,
    "financial_statement": _build_financial_statement,
    "gross_profit": _build_gross_profit,
    "laboratory_tests": _build_laboratory_tests,
    "radiology_scans": _build_radiology_scans,
    "pharmacy_sales": _build_pharmacy_sales,
    "admissions": _build_admissions,
    "branch_performance": _build_branch_performance,
    "department_inventory": _build_department_inventory,
}


def _parse_branch_filter(user, value):
    if not value:
        return None
    try:
        branch_id = int(value)
    except (TypeError, ValueError):
        return None

    allowed = Branch.objects.filter(pk=branch_id)
    if not user.can_view_all_branches:
        allowed = allowed.filter(pk=user.branch_id)
    return branch_id if allowed.exists() else None


def _department_filter_from_request(value):
    value = (value or "").strip().lower()
    return value if value in GROSS_PROFIT_SERVICE_TYPES else ""


def _report_query_filters(request, selected_report):
    if selected_report != "gross_profit":
        return {"branch_id": None, "department": ""}
    return {
        "branch_id": _parse_branch_filter(request.user, request.GET.get("branch")),
        "department": _department_filter_from_request(request.GET.get("department")),
    }


def _build_report(report_type, user, start, end, filters=None):
    builder = REPORT_BUILDERS.get(report_type)
    if not builder:
        raise Http404("Unknown report type")
    filters = filters or {}
    if report_type == "gross_profit":
        return builder(
            user,
            start,
            end,
            branch_id=filters.get("branch_id"),
            department=filters.get("department", ""),
        )
    return builder(user, start, end)


def _display_header(header):
    return header.replace("_", " ").title()


def _save_generated_report(request, report_type, export_format, start, end, row_count):
    if not request.user.branch_id:
        return
    GeneratedReport.objects.create(
        branch=request.user.branch,
        report_type=report_type,
        export_format=export_format,
        date_from=start,
        date_to=end,
        row_count=row_count,
        generated_by=request.user,
        file_path="",
    )


def _export_csv(report_label, headers, rows):
    response = HttpResponse(content_type="text/csv")
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    filename = f"{report_label.lower().replace(' ', '_')}_{timestamp}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([_display_header(h) for h in headers])
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return response


def _export_pdf(report_label, headers, rows, start, end):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        return HttpResponse("PDF export requires reportlab.", status=500)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"{report_label} Report")
    y -= 18
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Date Range: {start} to {end}")
    y -= 20
    pdf.drawString(40, y, " | ".join(_display_header(h) for h in headers))
    y -= 14

    for row in rows:
        line = " | ".join(str(row.get(h, "")) for h in headers)
        if len(line) > 160:
            line = f"{line[:157]}..."
        pdf.drawString(40, y, line)
        y -= 12
        if y < 40:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 10)

    pdf.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    filename = f"{report_label.lower().replace(' ', '_')}_{timestamp}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("reports", "view")
def index(request):
    selected_report = request.GET.get("report", "daily_visits")
    if selected_report not in REPORT_TYPES:
        selected_report = "daily_visits"

    date_from, date_to = _date_range_from_request(request)
    report_filters = _report_query_filters(request, selected_report)
    headers, rows = _build_report(
        selected_report,
        request.user,
        date_from,
        date_to,
        filters=report_filters,
    )

    rows_paginator = Paginator(rows, 20)
    data_page_obj = rows_paginator.get_page(request.GET.get("data_page"))
    rendered_rows = [
        [row.get(header, "") for header in headers] for row in data_page_obj.object_list
    ]

    history_queryset = branch_queryset_for_user(
        request.user,
        GeneratedReport.objects.select_related("generated_by", "branch").order_by(
            "-generated_at"
        ),
    )
    history_paginator = Paginator(history_queryset, 10)
    history_page_obj = history_paginator.get_page(request.GET.get("history_page"))
    branch_options = _report_branch_options(request.user)

    return render(
        request,
        "reports/index.html",
        {
            "report_types": REPORT_TYPES,
            "selected_report": selected_report,
            "selected_report_label": REPORT_TYPES[selected_report],
            "headers": headers,
            "rows": rendered_rows,
            "data_page_obj": data_page_obj,
            "history": history_page_obj.object_list,
            "history_page_obj": history_page_obj,
            "date_from": date_from,
            "date_to": date_to,
            "branch_options": branch_options,
            "gross_profit_department_options": GROSS_PROFIT_DEPARTMENT_LABELS,
            "selected_branch": report_filters["branch_id"] or "",
            "selected_department": report_filters["department"],
        },
    )


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("reports", "view")
def export_report(request):
    selected_report = request.GET.get("report", "daily_visits")
    if selected_report not in REPORT_TYPES:
        raise Http404("Unknown report type")

    export_format = request.GET.get("format", "csv").lower()
    if export_format not in {"csv", "pdf"}:
        raise Http404("Unsupported export format")

    date_from, date_to = _date_range_from_request(request)
    report_filters = _report_query_filters(request, selected_report)
    headers, rows = _build_report(
        selected_report,
        request.user,
        date_from,
        date_to,
        filters=report_filters,
    )
    report_label = REPORT_TYPES[selected_report]

    _save_generated_report(
        request,
        selected_report,
        export_format,
        date_from,
        date_to,
        len(rows),
    )

    if export_format == "pdf":
        return _export_pdf(report_label, headers, rows, date_from, date_to)
    return _export_csv(report_label, headers, rows)


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("reports", "view")
def profit_report(request):
    date_from, date_to = _date_range_from_request(request)
    selected_branch = _parse_branch_filter(request.user, request.GET.get("branch"))
    selected_department = _department_filter_from_request(request.GET.get("department"))

    qs = branch_queryset_for_user(
        request.user,
        InvoiceLineItem.objects.select_related("invoice").filter(
            invoice__date__date__range=(date_from, date_to)
        ),
    )
    if selected_branch:
        qs = qs.filter(invoice__branch_id=selected_branch)
    if selected_department:
        qs = qs.filter(service_type__in=GROSS_PROFIT_SERVICE_TYPES[selected_department])

    service_agg = (
        qs.values("service_type")
        .annotate(
            transactions=Count("id"),
            sales=Coalesce(Sum("amount"), Decimal("0.00")),
            cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
            profit=Coalesce(Sum("profit_amount"), Decimal("0.00")),
        )
        .order_by("service_type")
    )

    department_map = {
        "lab": "laboratory",
        "radiology": "radiology",
        "consultation": "consultation",
        "pharmacy": "pharmacy",
        "referral": "referral",
    }
    department_rows = {}
    for row in service_agg:
        department = department_map.get(row["service_type"], "general")
        entry = department_rows.setdefault(
            department,
            {
                "department": department,
                "transactions": 0,
                "sales": Decimal("0.00"),
                "cost": Decimal("0.00"),
                "profit": Decimal("0.00"),
            },
        )
        entry["transactions"] += row["transactions"]
        entry["sales"] += row["sales"]
        entry["cost"] += row["cost"]
        entry["profit"] += row["profit"]

    low_stock_alerts = list(
        branch_queryset_for_user(
            request.user,
            Item.objects.filter(is_active=True)
            .exclude(service_type="")
            .annotate(total_quantity=Coalesce(Sum("batches__quantity_remaining"), 0))
            .filter(total_quantity__lte=F("reorder_level"))
            .order_by("total_quantity", "item_name"),
        )
    )
    if selected_department:
        low_stock_alerts = [
            item
            for item in low_stock_alerts
            if item.mapped_department == selected_department
        ]

    totals = qs.aggregate(
        total_sales=Coalesce(Sum("amount"), Decimal("0.00")),
        total_cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
        total_profit=Coalesce(Sum("profit_amount"), Decimal("0.00")),
    )
    branch_options = _report_branch_options(request.user)

    return render(
        request,
        "reports/profit.html",
        {
            "date_from": date_from,
            "date_to": date_to,
            "service_rows": list(service_agg),
            "department_rows": sorted(
                department_rows.values(), key=lambda x: x["department"]
            ),
            "low_stock_alerts": low_stock_alerts,
            "totals": totals,
            "branch_options": branch_options,
            "gross_profit_department_options": GROSS_PROFIT_DEPARTMENT_LABELS,
            "selected_branch": selected_branch or "",
            "selected_department": selected_department,
        },
    )


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("reports", "view")
def laboratory_profitability_report(request):
    date_from, date_to = _date_range_from_request(request)
    selected_branch = _parse_branch_filter(request.user, request.GET.get("branch"))
    rows, totals = _build_laboratory_profitability_detail(
        request.user,
        date_from,
        date_to,
        branch_id=selected_branch,
    )
    page_obj = Paginator(rows, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "reports/department_profitability.html",
        {
            "report_title": "Laboratory Profitability",
            "report_description": (
                "Each paid laboratory test with the patient charged fee, actual consumable cost, and gross profit."
            ),
            "department": "laboratory",
            "rows": page_obj.object_list,
            "page_obj": page_obj,
            "totals": totals,
            "date_from": date_from,
            "date_to": date_to,
            "branch_options": _report_branch_options(request.user),
            "selected_branch": selected_branch or "",
        },
    )


@login_required
@role_required("receptionist", "system_admin", "director")
@module_permission_required("reports", "view")
def radiology_profitability_report(request):
    date_from, date_to = _date_range_from_request(request)
    selected_branch = _parse_branch_filter(request.user, request.GET.get("branch"))
    rows, totals = _build_radiology_profitability_detail(
        request.user,
        date_from,
        date_to,
        branch_id=selected_branch,
    )
    page_obj = Paginator(rows, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "reports/department_profitability.html",
        {
            "report_title": "Radiology Profitability",
            "report_description": (
                "Each paid imaging request with the patient charged fee, actual consumable cost, and gross profit."
            ),
            "department": "radiology",
            "rows": page_obj.object_list,
            "page_obj": page_obj,
            "totals": totals,
            "date_from": date_from,
            "date_to": date_to,
            "branch_options": _report_branch_options(request.user),
            "selected_branch": selected_branch or "",
        },
    )
