from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.inventory.forms import MedicalStoreEntryForm
from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    InventoryStoreProfile,
    Item,
    Supplier,
)
from apps.pharmacy.models import MedicalStoreRequest
from apps.pharmacy.services import sync_medicine_catalog_for_item
from apps.inventory.services import fulfill_store_request, record_stock_entry


STORE_LABELS = {
    "all": "All Stores",
    "pharmacy": "Pharmacy Store",
    "laboratory": "Laboratory Store",
    "radiology": "Radiology Overview",
    "xray": "X-Ray Store",
    "ultrasound": "Ultrasound Store",
    "general": "General Store",
}

REQUEST_STATUS_CHOICES = ["pending", "approved", "fulfilled", "rejected"]
MANAGED_STORE_CODES = ["pharmacy", "laboratory", "xray", "ultrasound", "general"]
RADIOLOGY_STORE_CODES = ["xray", "ultrasound"]


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _log_store_request_event(request, store_request, action, remarks=""):
    details = {
        "path": request.path,
        "method": request.method,
        "requested_for": store_request.requested_for,
        "requested_unit": store_request.requested_unit,
        "status": store_request.status,
        "quantity_requested": store_request.quantity_requested,
    }
    if remarks:
        details["remarks"] = remarks

    try:
        AuditLog.objects.create(
            user=request.user,
            branch=getattr(request, "branch", None)
            or getattr(request.user, "branch", None),
            action=f"inventory.store_request.{action}",
            object_type="medical_store_request",
            object_id=str(store_request.pk),
            details=str(details),
            ip_address=_client_ip(request),
        )
    except Exception:
        pass


def _normalize_store_filter(value):
    value = (value or "all").strip().lower()
    return value if value in STORE_LABELS else "all"


def _normalize_request_unit(value):
    value = (value or "").strip().lower()
    return value if value in {"xray", "ultrasound"} else ""


def _normalize_status_filter(value):
    value = (value or "pending").strip().lower()
    return value if value in {"all", *REQUEST_STATUS_CHOICES} else "pending"


def _dashboard_url_for_store(store):
    if store and store != "all":
        return redirect("inventory:medical_store_dashboard_by_store", store=store)
    return redirect("inventory:medical_store_dashboard")


def _entry_url_for_store(store):
    return reverse("inventory:medical_store_entry_by_store", args=[store])


def _default_store_for_user(user):
    managed_store = None
    if getattr(user, "branch_id", None):
        managed_store = (
            InventoryStoreProfile.objects.filter(
                branch_id=user.branch_id,
                manager=user,
                store_department__in=MANAGED_STORE_CODES,
            )
            .values_list("store_department", flat=True)
            .first()
        )
    if managed_store:
        return managed_store

    if user.is_superuser or user.role in {"system_admin", "director"}:
        return "all"

    return {
        "pharmacist": "pharmacy",
        "lab_technician": "laboratory",
        "radiology_technician": getattr(user, "radiology_unit_assignment", "")
        or "radiology",
    }.get(user.role, "pharmacy")


def _store_profiles_for_user(user):
    if not getattr(user, "branch_id", None):
        return {}

    existing_profiles = {
        profile.store_department: profile
        for profile in InventoryStoreProfile.objects.select_related("manager").filter(
            branch_id=user.branch_id,
            store_department__in=MANAGED_STORE_CODES,
        )
    }
    return {
        store: existing_profiles.get(store)
        or InventoryStoreProfile(branch=user.branch, store_department=store)
        for store in MANAGED_STORE_CODES
    }


def _normalize_store_code_or_none(value):
    normalized = _normalize_store_filter(value)
    return normalized if normalized in MANAGED_STORE_CODES else ""


def _build_medical_store_context(user, filters=None):
    filters = filters or {}
    today = timezone.localdate()
    expiry_threshold = today + timedelta(days=30)
    store_filter = _normalize_store_filter(filters.get("store"))

    item_queryset = Item.objects.select_related("category", "brand")
    batch_queryset = Batch.objects.select_related("item", "supplier")
    if store_filter in {"pharmacy", "laboratory", "xray", "ultrasound", "general"}:
        item_queryset = item_queryset.filter(store_department=store_filter)
        batch_queryset = batch_queryset.filter(item__store_department=store_filter)
    elif store_filter == "radiology":
        item_queryset = item_queryset.filter(store_department__in=RADIOLOGY_STORE_CODES)
        batch_queryset = batch_queryset.filter(
            item__store_department__in=RADIOLOGY_STORE_CODES
        )

    medical_items = branch_queryset_for_user(
        user,
        item_queryset.order_by("item_name"),
    )[:200]
    low_stock_items = [
        item for item in medical_items if item.quantity_on_hand <= item.reorder_level
    ]
    expiring_batches = branch_queryset_for_user(
        user,
        batch_queryset.select_related("item")
        .filter(
            quantity_remaining__gt=0,
            exp_date__gte=today,
            exp_date__lte=expiry_threshold,
        )
        .order_by("exp_date"),
    )[:50]
    expired_batches = branch_queryset_for_user(
        user,
        batch_queryset.select_related("item")
        .filter(
            quantity_remaining__gt=0,
            exp_date__lt=today,
        )
        .order_by("exp_date"),
    )[:50]
    current_stock_batches = branch_queryset_for_user(
        user,
        batch_queryset.filter(quantity_remaining__gt=0).order_by("-created_at"),
    )

    item_q = (filters.get("item") or "").strip()
    batch_q = (filters.get("batch") or "").strip()
    supplier_q = (filters.get("supplier") or "").strip()

    if item_q:
        current_stock_batches = current_stock_batches.filter(
            item__item_name__icontains=item_q
        )
    if batch_q:
        current_stock_batches = current_stock_batches.filter(
            batch_number__icontains=batch_q
        )
    if supplier_q:
        current_stock_batches = current_stock_batches.filter(
            supplier__name__icontains=supplier_q
        )

    current_stock_batches = current_stock_batches[:200]

    total_units = 0
    total_equivalent_packs = Decimal("0")
    total_cost_value = Decimal("0.00")
    total_retail_value = Decimal("0.00")
    metric_batch_queryset = batch_queryset.filter(quantity_remaining__gt=0)
    for batch in branch_queryset_for_user(user, metric_batch_queryset):
        total_units += batch.quantity_remaining
        if batch.pack_size_units > 0:
            total_equivalent_packs += Decimal(batch.quantity_remaining) / Decimal(
                batch.pack_size_units
            )
        total_cost_value += Decimal(batch.quantity_remaining) * batch.unit_cost
        total_retail_value += (
            Decimal(batch.quantity_remaining) * batch.selling_price_per_unit
        )

    return {
        "medical_items": medical_items,
        "low_stock_items": low_stock_items,
        "expiring_batches": expiring_batches,
        "expired_batches": expired_batches,
        "current_stock_batches": current_stock_batches,
        "stock_filters": {
            "item": item_q,
            "batch": batch_q,
            "supplier": supplier_q,
            "store": store_filter,
        },
        "store_choices": Item.STORE_DEPARTMENT_CHOICES,
        "medical_store_snapshot": {
            "low_stock_count": len(low_stock_items),
            "expiring_count": expiring_batches.count(),
            "expired_count": expired_batches.count(),
            "total_units": total_units,
            "equivalent_packs": total_equivalent_packs,
            "total_cost_value": total_cost_value,
            "total_retail_value": total_retail_value,
        },
    }


def _store_requests_context(
    user, store_filter="all", status_filter="pending", request_unit=""
):
    store_filter = _normalize_store_filter(store_filter)
    status_filter = _normalize_status_filter(status_filter)
    request_unit = _normalize_request_unit(request_unit)

    request_queryset = branch_queryset_for_user(
        user,
        MedicalStoreRequest.objects.select_related(
            "requested_by", "handled_by", "item", "stock_item"
        ).order_by("created_at"),
    )
    if store_filter in {"pharmacy", "laboratory"}:
        request_queryset = request_queryset.filter(requested_for=store_filter)
    if store_filter == "radiology":
        request_queryset = request_queryset.filter(requested_for="radiology")
    if store_filter in RADIOLOGY_STORE_CODES:
        request_queryset = request_queryset.filter(
            requested_for="radiology",
            requested_unit=store_filter,
        )
    elif store_filter == "radiology" and request_unit:
        request_queryset = request_queryset.filter(requested_unit=request_unit)
    if status_filter != "all":
        request_queryset = request_queryset.filter(status=status_filter)

    base_summary_queryset = branch_queryset_for_user(
        user,
        MedicalStoreRequest.objects.all(),
    )
    if store_filter in {"pharmacy", "laboratory"}:
        base_summary_queryset = base_summary_queryset.filter(requested_for=store_filter)
    if store_filter == "radiology":
        base_summary_queryset = base_summary_queryset.filter(requested_for="radiology")
    if store_filter in RADIOLOGY_STORE_CODES:
        base_summary_queryset = base_summary_queryset.filter(
            requested_for="radiology",
            requested_unit=store_filter,
        )
    elif store_filter == "radiology" and request_unit:
        base_summary_queryset = base_summary_queryset.filter(
            requested_unit=request_unit
        )

    request_summary = {
        status: base_summary_queryset.filter(status=status).count()
        for status in REQUEST_STATUS_CHOICES
    }

    return {
        "store_requests": request_queryset[:50],
        "request_summary": request_summary,
        "status_filter": status_filter,
        "request_unit": request_unit,
        "request_unit_choices": MedicalStoreRequest.REQUESTED_UNIT_CHOICES[1:],
        "selected_store": store_filter,
        "selected_store_label": STORE_LABELS[store_filter],
        "store_navigation": [
            ("all", STORE_LABELS["all"]),
            ("pharmacy", STORE_LABELS["pharmacy"]),
            ("laboratory", STORE_LABELS["laboratory"]),
            ("radiology", STORE_LABELS["radiology"]),
            ("xray", STORE_LABELS["xray"]),
            ("ultrasound", STORE_LABELS["ultrasound"]),
            ("general", STORE_LABELS["general"]),
        ],
        "can_manage_store_requests": user.is_superuser
        or user.role
        in {
            "pharmacist",
            "lab_technician",
            "radiology_technician",
            "system_admin",
            "director",
        },
    }


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "view")
def index(request):
    default_store = _default_store_for_user(request.user)
    if default_store == "all":
        return redirect("inventory:medical_store_dashboard")
    return redirect("inventory:medical_store_dashboard_by_store", store=default_store)


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "view")
def medical_store_dashboard(request, store=None):
    filters = {
        "item": request.GET.get("item", ""),
        "batch": request.GET.get("batch", ""),
        "supplier": request.GET.get("supplier", ""),
        "store": store or request.GET.get("store", "all"),
    }
    medical_store_context = _build_medical_store_context(request.user, filters=filters)
    request_context = _store_requests_context(
        request.user,
        store_filter=medical_store_context["stock_filters"]["store"],
        status_filter=request.GET.get("request_status", "pending"),
        request_unit=request.GET.get("request_unit", ""),
    )
    store_profiles = _store_profiles_for_user(request.user)
    selected_store = request_context["selected_store"]
    current_store_profile = (
        store_profiles.get(selected_store)
        if selected_store in MANAGED_STORE_CODES
        else None
    )
    store_cards = []
    for store_code in MANAGED_STORE_CODES:
        profile = store_profiles.get(store_code)
        store_cards.append(
            {
                "code": store_code,
                "label": STORE_LABELS[store_code],
                "manager": getattr(profile, "manager", None),
                "location": getattr(profile, "location", ""),
                "notes": getattr(profile, "notes", ""),
                "dashboard_url": reverse(
                    "inventory:medical_store_dashboard_by_store", args=[store_code]
                ),
                "entry_url": _entry_url_for_store(store_code),
            }
        )

    return render(
        request,
        "inventory/medical_store_dashboard.html",
        {
            **medical_store_context,
            **request_context,
            "store_profiles": store_profiles,
            "current_store_profile": current_store_profile,
            "store_cards": store_cards,
            "selected_store_entry_url": (
                _entry_url_for_store(selected_store)
                if selected_store in MANAGED_STORE_CODES
                else ""
            ),
        },
    )


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "create")
def medical_store_entry(request, store=None):
    store = _normalize_store_code_or_none(store)
    if not store:
        default_store = _default_store_for_user(request.user)
        if default_store == "all":
            default_store = "pharmacy"
        return redirect("inventory:medical_store_entry_by_store", store=default_store)

    current_store_profile = _store_profiles_for_user(request.user).get(store)
    if request.method == "POST":
        form = MedicalStoreEntryForm(
            request.POST,
            user=request.user,
            store_department=store,
        )
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                with transaction.atomic():
                    category = form.cleaned_data["category"]
                    if not category:
                        category, _ = Category.objects.get_or_create(
                            branch=request.user.branch,
                            name=form.cleaned_data["_new_category_name"],
                        )

                    brand = form.cleaned_data["brand"]
                    if not brand:
                        brand, _ = Brand.objects.get_or_create(
                            branch=request.user.branch,
                            name=form.cleaned_data["_new_brand_name"],
                        )

                    supplier = form.cleaned_data["supplier"]
                    if not supplier and form.cleaned_data.get("_new_supplier_name"):
                        supplier, _ = Supplier.objects.get_or_create(
                            branch=request.user.branch,
                            name=form.cleaned_data["_new_supplier_name"],
                            defaults={
                                "contact": form.cleaned_data.get(
                                    "supplier_contact", ""
                                ),
                                "address": form.cleaned_data.get(
                                    "supplier_address", ""
                                ),
                            },
                        )

                    item = (
                        Item.objects.filter(
                            branch=request.user.branch,
                            item_name=form.cleaned_data["item_name"],
                            strength=form.cleaned_data.get("strength", ""),
                            brand=brand,
                            store_department=store,
                        )
                        .order_by("id")
                        .first()
                    )
                    if not item:
                        item = Item.objects.create(
                            branch=request.user.branch,
                            item_name=form.cleaned_data["item_name"],
                            generic_name=form.cleaned_data.get("generic_name", ""),
                            category=category,
                            brand=brand,
                            dosage_form=form.cleaned_data["dosage_form"],
                            strength=form.cleaned_data.get("strength", ""),
                            unit_of_measure=form.cleaned_data["unit_of_measure"],
                            pack_size=form.cleaned_data.get("pack_size", ""),
                            barcode=form.cleaned_data.get("barcode", ""),
                            store_department=store,
                            service_type=form.cleaned_data.get("service_type", ""),
                            service_code=form.cleaned_data.get("service_code", ""),
                            reorder_level=form.cleaned_data["reorder_level"],
                            description=form.cleaned_data.get("description", ""),
                            is_active=True,
                            default_pack_size_units=form.cleaned_data[
                                "pack_size_units"
                            ],
                        )
                    else:
                        update_fields = []
                        updates = {
                            "generic_name": form.cleaned_data.get("generic_name", ""),
                            "category": category,
                            "dosage_form": form.cleaned_data["dosage_form"],
                            "unit_of_measure": form.cleaned_data["unit_of_measure"],
                            "pack_size": form.cleaned_data.get("pack_size", ""),
                            "barcode": form.cleaned_data.get("barcode", ""),
                            "service_type": form.cleaned_data.get("service_type", ""),
                            "service_code": form.cleaned_data.get("service_code", ""),
                            "reorder_level": form.cleaned_data["reorder_level"],
                            "description": form.cleaned_data.get("description", ""),
                            "default_pack_size_units": form.cleaned_data[
                                "pack_size_units"
                            ],
                        }
                        for field_name, field_value in updates.items():
                            if getattr(item, field_name) != field_value:
                                setattr(item, field_name, field_value)
                                update_fields.append(field_name)

                        if update_fields:
                            item.save(update_fields=update_fields + ["updated_at"])

                    duplicate_batch = Batch.objects.filter(
                        branch=request.user.branch,
                        item=item,
                        batch_number=form.cleaned_data["batch_number"],
                    ).exists()
                    if duplicate_batch:
                        form.add_error(
                            "batch_number",
                            "This batch number already exists for the selected item.",
                        )
                    else:
                        try:
                            batch = Batch.objects.create(
                                branch=request.user.branch,
                                item=item,
                                batch_number=form.cleaned_data["batch_number"],
                                mfg_date=form.cleaned_data.get("mfg_date"),
                                exp_date=form.cleaned_data["exp_date"],
                                pack_size_units=form.cleaned_data["pack_size_units"],
                                packs_received=form.cleaned_data["packs_received"],
                                quantity_received=form.cleaned_data[
                                    "quantity_received"
                                ],
                                purchase_price_per_pack=form.cleaned_data[
                                    "purchase_price_per_pack"
                                ],
                                purchase_price_total=form.cleaned_data[
                                    "purchase_price_total"
                                ],
                                target_margin=form.cleaned_data["target_profit_margin"],
                                supplier=supplier,
                                barcode=form.cleaned_data.get("batch_barcode", ""),
                                weight=form.cleaned_data.get("weight", ""),
                                volume=form.cleaned_data.get("volume", ""),
                                created_by=request.user,
                            )
                            record_stock_entry(
                                batch,
                                request.user,
                                reference=f"Medical store stock entry {batch.batch_number}",
                            )
                            sync_medicine_catalog_for_item(item)
                        except ValidationError as exc:
                            for field, messages_list in exc.message_dict.items():
                                if field == "__all__":
                                    form.add_error(None, messages_list[0])
                                elif field in form.fields:
                                    form.add_error(field, messages_list[0])
                                else:
                                    form.add_error(None, messages_list[0])

                if not form.errors:
                    messages.success(
                        request,
                        f"{STORE_LABELS[store]} stock entry saved successfully.",
                    )
                    return redirect(
                        "inventory:medical_store_dashboard_by_store", store=store
                    )
    else:
        form = MedicalStoreEntryForm(user=request.user, store_department=store)

    return render(
        request,
        "inventory/medical_store_entry_form.html",
        {
            "form": form,
            "page_title": f"{STORE_LABELS[store]} Stock Entry",
            "submit_label": "Save Stock Entry",
            "preview_unit_cost": form.preview_unit_cost,
            "preview_selling_price": form.preview_selling_price,
            "preview_profit_per_unit": form.preview_profit_margin_unit,
            "store_label": STORE_LABELS[store],
            "store_code": store,
            "current_store_profile": current_store_profile,
        },
    )


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "update")
def fulfill_pharmacy_request(request, pk):
    return _update_store_request_status(request, pk, "fulfill")


def _update_store_request_status(request, pk, action):
    if request.method != "POST":
        return redirect("inventory:index")

    store_request = get_object_or_404(MedicalStoreRequest, pk=pk)
    if not branch_queryset_for_user(
        request.user, MedicalStoreRequest.objects.filter(pk=pk)
    ).exists():
        return redirect("inventory:index")

    current_status = store_request.status
    if action in {"approve", "reject"} and current_status != "pending":
        messages.info(request, "This request has already been handled.")
        return redirect("inventory:index")
    if action == "fulfill" and current_status not in {"pending", "approved"}:
        messages.info(
            request, "This request cannot be fulfilled from its current status."
        )
        return redirect("inventory:index")

    action = (action or "").strip().lower()
    next_url = request.POST.get("next", "").strip()
    redirect_target = redirect("inventory:medical_store_dashboard")
    if next_url.startswith("/"):
        redirect_target = redirect(next_url)

    if action not in {"approve", "reject", "fulfill"}:
        messages.error(request, "Unknown store-request action.")
        return redirect_target

    remarks = (request.POST.get("remarks") or "").strip()
    if action in {"approve", "reject"} and not remarks:
        messages.error(
            request,
            f"{action.title()} remarks are required so the fulfillment decision is traceable.",
        )
        return redirect_target

    if action == "fulfill":
        try:
            with transaction.atomic():
                fulfill_store_request(store_request, request.user, remarks=remarks)
        except ValidationError as exc:
            error_msg = exc.message if hasattr(exc, "message") else str(exc)
            messages.error(request, f"Cannot fulfill request: {error_msg}")
            return redirect_target
    else:
        store_request.status = {
            "approve": "approved",
            "reject": "rejected",
        }[action]
        if action in {"approve", "reject"}:
            store_request.decision_remarks = remarks
        store_request.handled_by = request.user
        store_request.handled_at = timezone.now()
        store_request.save(
            update_fields=[
                "status",
                "decision_remarks",
                "handled_by",
                "handled_at",
                "updated_at",
            ]
        )

    _log_store_request_event(request, store_request, action, remarks=remarks)

    action_label = {
        "approve": "approved",
        "reject": "rejected",
        "fulfill": "fulfilled",
    }[action]
    messages.success(
        request,
        f"{store_request.request_scope_label} request {action_label}. Live stock remains managed through medical stores under inventory.",
    )
    return redirect_target


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "update")
def update_store_request_status(request, pk, action):
    return _update_store_request_status(request, pk, action)


@login_required
@role_required("pharmacist", "system_admin", "director")
@module_permission_required("inventory", "create")
def create_item(request):
    messages.warning(
        request,
        "Direct inventory stock items are disabled. Manage stock through Medical Store Entry.",
    )
    return redirect("inventory:medical_store_dashboard")


@login_required
@role_required(
    "pharmacist",
    "lab_technician",
    "radiology_technician",
    "system_admin",
    "director",
)
@module_permission_required("inventory", "update")
def issue_stock(request):
    messages.warning(
        request,
        "Direct stock issue from legacy inventory items is disabled. Departments should be served from medical stores workflows.",
    )
    return redirect("inventory:medical_store_dashboard")
