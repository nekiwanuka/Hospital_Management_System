from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import (
    Batch,
    Dispense,
    DispenseItem,
    Item,
    ServiceConsumption,
    StockMovement,
)


def _normalize_code(value):
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def store_department_for_service(service_type, service_code=""):
    normalized_code = _normalize_code(service_code)
    mapping = {
        "lab": "laboratory",
        "consultation": "general",
    }
    if (service_type or "").strip().lower() == "radiology":
        if "ultrasound" in normalized_code:
            return "ultrasound"
        if "xray" in normalized_code or "x_ray" in normalized_code:
            return "xray"
        return "radiology"
    return mapping.get((service_type or "").strip().lower(), "general")


def service_stock_item(branch, service_type, service_code):
    if not branch or not service_code:
        return None

    code = _normalize_code(service_code)
    store_department = store_department_for_service(service_type, code)
    queryset = Item.objects.filter(
        branch=branch,
        service_type=service_type,
        service_code=code,
        is_active=True,
    )
    if store_department:
        preferred_item = (
            queryset.filter(store_department=store_department)
            .order_by("-updated_at")
            .first()
        )
        if preferred_item:
            return preferred_item
    return queryset.order_by("-updated_at").first()


def service_stock_cost(branch, service_type, service_code):
    """Resolve stock cost for a billable service from inventory master item."""
    item = service_stock_item(branch, service_type, service_code)
    if not item:
        return Decimal("0.00")

    batch = (
        Batch.objects.filter(
            branch=branch,
            item=item,
            quantity_remaining__gt=0,
            exp_date__gte=timezone.localdate(),
        )
        .order_by("exp_date", "date_received", "id")
        .first()
    )
    if batch:
        return batch.unit_cost

    fallback_batch = (
        Batch.objects.filter(branch=branch, item=item)
        .order_by("-date_received", "-id")
        .first()
    )
    return fallback_batch.unit_cost if fallback_batch else Decimal("0.00")


def service_consumptions_queryset(
    branch, source_model, source_id, *, include_reversed=False
):
    queryset = ServiceConsumption.objects.select_related(
        "item", "batch", "consumed_by"
    ).filter(
        branch=branch,
        source_model=source_model,
        source_id=source_id,
    )
    if not include_reversed:
        queryset = queryset.filter(reversed_at__isnull=True)
    return queryset


def has_service_consumptions(branch, source_model, source_id):
    return service_consumptions_queryset(branch, source_model, source_id).exists()


def summarized_service_consumptions(branch, source_model, source_id):
    queryset = service_consumptions_queryset(branch, source_model, source_id)
    rows = list(
        queryset.values("item__item_name", "item__unit_of_measure")
        .annotate(
            quantity=Coalesce(Sum("quantity"), 0),
            total_cost=Coalesce(Sum("total_cost"), Decimal("0.00")),
        )
        .order_by("item__item_name")
    )
    total_cost = queryset.aggregate(total=Coalesce(Sum("total_cost"), Decimal("0.00")))[
        "total"
    ]
    return rows, total_cost


def reverse_service_consumptions(
    *,
    branch,
    source_model,
    source_id,
    reversed_by,
    reason,
    reference="",
):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A correction reason is required before reversal.")

    with transaction.atomic():
        consumptions = list(
            service_consumptions_queryset(
                branch,
                source_model,
                source_id,
            ).select_for_update()
        )
        if not consumptions:
            raise ValidationError("There are no active consumptions to reverse.")

        now = timezone.now()
        for consumption in consumptions:
            batch = consumption.batch
            batch.quantity_remaining += consumption.quantity
            batch.save(update_fields=["quantity_remaining", "updated_at"])

            reversal_reference = (
                reference or f"Consumable correction for {source_model} #{source_id}"
            )
            StockMovement.objects.create(
                branch=branch,
                item=consumption.item,
                batch=batch,
                movement_type="IN",
                quantity=consumption.quantity,
                reference=reversal_reference,
                user=reversed_by,
            )
            consumption.reversed_at = now
            consumption.reversed_by = reversed_by
            consumption.reversal_reason = reason
            consumption.reversal_reference = reversal_reference
            consumption.save(
                update_fields=[
                    "reversed_at",
                    "reversed_by",
                    "reversal_reason",
                    "reversal_reference",
                    "updated_at",
                ]
            )

        sync_service_consumption_financials(branch, source_model, source_id)

    return consumptions


def _service_consumption_code_for_item(item):
    return _normalize_code(item.service_code or item.item_name or f"item_{item.pk}")


def allocate_selected_item_stock(
    *,
    branch,
    item,
    quantity,
    service_type,
    consumed_by,
    source_model,
    source_id,
    reference="",
):
    if not branch or not item or quantity <= 0:
        return []

    if item.branch_id != branch.id:
        raise ValidationError(
            f"{item.item_name} does not belong to the selected branch."
        )

    with transaction.atomic():
        batches = list(_eligible_fifo_batches(item))
        available = sum(batch.quantity_remaining for batch in batches)
        if available < quantity:
            raise ValidationError(
                f"Insufficient stock for {item.item_name}. Available {available}, required {quantity}."
            )

        remaining = quantity
        allocations = []
        for batch in batches:
            if remaining <= 0:
                break

            take_qty = min(remaining, batch.quantity_remaining)
            batch.quantity_remaining -= take_qty
            batch.save(update_fields=["quantity_remaining", "updated_at"])

            movement_reference = reference or f"Service consumption: {item.item_name}"
            StockMovement.objects.create(
                branch=branch,
                item=item,
                batch=batch,
                movement_type="OUT",
                quantity=take_qty,
                reference=movement_reference,
                user=consumed_by,
            )

            total_cost = (batch.unit_cost * Decimal(take_qty)).quantize(Decimal("0.01"))
            ServiceConsumption.objects.create(
                branch=branch,
                item=item,
                batch=batch,
                service_type=service_type,
                service_code=_service_consumption_code_for_item(item),
                source_model=source_model,
                source_id=source_id,
                quantity=take_qty,
                unit_cost_snapshot=batch.unit_cost,
                total_cost=total_cost,
                reference=movement_reference,
                consumed_by=consumed_by,
            )
            allocations.append(
                {
                    "item": item,
                    "batch": batch,
                    "quantity": take_qty,
                    "unit_cost": batch.unit_cost,
                    "total_cost": total_cost,
                }
            )
            remaining -= take_qty

    return allocations


def sync_service_consumption_financials(branch, source_model, source_id):
    from apps.billing.models import InvoiceLineItem
    from apps.laboratory.models import LabRequest
    from apps.radiology.models import ImagingRequest

    queryset = service_consumptions_queryset(branch, source_model, source_id)
    total_cost = queryset.aggregate(total=Coalesce(Sum("total_cost"), Decimal("0.00")))[
        "total"
    ]
    unit_cost_snapshot = total_cost.quantize(Decimal("0.0001"))
    total_cost = total_cost.quantize(Decimal("0.01"))

    line_item = (
        InvoiceLineItem.objects.filter(
            branch=branch,
            source_model=source_model,
            source_id=source_id,
        )
        .select_related("invoice")
        .order_by("-id")
        .first()
    )
    profit_amount = Decimal("0.00")
    if line_item:
        profit_amount = (line_item.amount - total_cost).quantize(Decimal("0.01"))
        line_item.unit_cost = total_cost
        line_item.total_cost = total_cost
        line_item.profit_amount = profit_amount
        line_item.stock_deducted_at = timezone.now() if total_cost > 0 else None
        line_item.save(
            update_fields=[
                "unit_cost",
                "total_cost",
                "profit_amount",
                "stock_deducted_at",
                "updated_at",
            ]
        )

    if source_model == "lab":
        LabRequest.objects.filter(branch=branch, pk=source_id).update(
            unit_cost_snapshot=unit_cost_snapshot,
            total_cost_snapshot=total_cost,
            profit_amount=profit_amount,
        )
    elif source_model == "radiology":
        ImagingRequest.objects.filter(branch=branch, pk=source_id).update(
            unit_cost_snapshot=unit_cost_snapshot,
            total_cost_snapshot=total_cost,
            profit_amount=profit_amount,
        )

    return total_cost, profit_amount


def record_selected_service_items(
    *,
    branch,
    service_type,
    source_model,
    source_id,
    selections,
    consumed_by,
    reference="",
    store_department="",
):
    if not selections:
        raise ValidationError("Select at least one stock item to use for this patient.")

    expected_store = store_department or store_department_for_service(service_type)
    with transaction.atomic():
        if has_service_consumptions(branch, source_model, source_id):
            raise ValidationError(
                "Consumables for this patient test have already been recorded."
            )

        allocations = []
        for selection in selections:
            item = selection["item"]
            quantity = selection["quantity"]
            if expected_store and item.store_department != expected_store:
                raise ValidationError(
                    f"{item.item_name} is not stocked under the {expected_store} store."
                )
            allocations.extend(
                allocate_selected_item_stock(
                    branch=branch,
                    item=item,
                    quantity=quantity,
                    service_type=service_type,
                    consumed_by=consumed_by,
                    source_model=source_model,
                    source_id=source_id,
                    reference=reference,
                )
            )

        sync_service_consumption_financials(branch, source_model, source_id)
        return allocations


def allocate_service_stock(
    branch,
    service_type,
    service_code,
    quantity=1,
    consumed_by=None,
    source_model="",
    source_id=None,
    reference="",
):
    if not branch or not service_code or quantity <= 0:
        return []

    code = _normalize_code(service_code)
    with transaction.atomic():
        item = service_stock_item(branch, service_type, code)

        if not item:
            raise ValidationError(
                f"Stock mapping missing for {service_type} service code '{code}'."
            )

        batches = list(_eligible_fifo_batches(item))
        available = sum(batch.quantity_remaining for batch in batches)
        if available < quantity:
            raise ValidationError(
                f"Insufficient stock for {item.item_name}. Available {available}, required {quantity}."
            )

        remaining = quantity
        allocations = []
        for batch in batches:
            if remaining <= 0:
                break

            take_qty = min(remaining, batch.quantity_remaining)
            batch.quantity_remaining -= take_qty
            batch.save(update_fields=["quantity_remaining", "updated_at"])

            movement_reference = (
                reference or f"Service consumption: {service_type}/{code}"
            )
            if consumed_by is not None:
                StockMovement.objects.create(
                    branch=branch,
                    item=item,
                    batch=batch,
                    movement_type="OUT",
                    quantity=take_qty,
                    reference=movement_reference,
                    user=consumed_by,
                )

            total_cost = (batch.unit_cost * Decimal(take_qty)).quantize(Decimal("0.01"))
            allocations.append(
                {
                    "item": item,
                    "batch": batch,
                    "quantity": take_qty,
                    "unit_cost": batch.unit_cost,
                    "total_cost": total_cost,
                    "reference": movement_reference,
                }
            )

            if consumed_by is not None and source_model and source_id:
                ServiceConsumption.objects.create(
                    branch=branch,
                    item=item,
                    batch=batch,
                    service_type=service_type,
                    service_code=code,
                    source_model=source_model,
                    source_id=source_id,
                    quantity=take_qty,
                    unit_cost_snapshot=batch.unit_cost,
                    total_cost=total_cost,
                    reference=movement_reference,
                    consumed_by=consumed_by,
                )

            remaining -= take_qty

        return allocations


def consume_service_stock(
    branch, service_type, service_code, quantity=1, consumed_by=None
):
    """Deduct stock for a billed service from active mapped stock item."""
    allocations = allocate_service_stock(
        branch,
        service_type,
        service_code,
        quantity=quantity,
        consumed_by=consumed_by,
    )
    return allocations[0]["item"] if allocations else None


def record_stock_entry(batch, user, reference=""):
    """Create an IN movement for a newly received batch."""
    return StockMovement.objects.create(
        branch=batch.branch,
        item=batch.item,
        batch=batch,
        movement_type="IN",
        quantity=batch.quantity_received,
        reference=reference or f"Batch {batch.batch_number} received",
        user=user,
    )


def _eligible_fifo_batches(item):
    return (
        Batch.objects.select_for_update()
        .filter(
            branch=item.branch,
            item=item,
            quantity_remaining__gt=0,
            exp_date__gte=timezone.localdate(),
        )
        .order_by("exp_date", "date_received", "id")
    )


def dispense_item_fifo(
    *,
    dispense,
    item,
    quantity,
    dispensed_by,
    reference="",
    unit_price=None,
):
    """Dispense stock using FEFO/FIFO rule (earliest expiry first)."""
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")

    with transaction.atomic():
        batches = list(_eligible_fifo_batches(item))
        available = sum(batch.quantity_remaining for batch in batches)
        if available < quantity:
            raise ValidationError(
                f"Insufficient non-expired stock for {item.item_name}. "
                f"Available {available}, requested {quantity}."
            )

        remaining = quantity
        created_items = []
        for batch in batches:
            if remaining <= 0:
                break

            take_qty = min(remaining, batch.quantity_remaining)
            batch.quantity_remaining -= take_qty
            batch.save(update_fields=["quantity_remaining", "updated_at"])

            chosen_price = (
                unit_price if unit_price is not None else batch.selling_price_per_unit
            )
            disp_item = DispenseItem.objects.create(
                branch=dispense.branch,
                dispense=dispense,
                item=item,
                batch=batch,
                quantity=take_qty,
                unit_price=chosen_price,
            )
            created_items.append(disp_item)

            StockMovement.objects.create(
                branch=dispense.branch,
                item=item,
                batch=batch,
                movement_type="OUT",
                quantity=take_qty,
                reference=reference or f"Dispense #{dispense.pk}",
                user=dispensed_by,
            )

            remaining -= take_qty

    return created_items


def create_dispense_with_items(
    *, branch, patient, dispensed_by, item_lines, reference=""
):
    """Create dispense transaction and allocate quantities batch-by-batch."""
    if not item_lines:
        raise ValidationError("At least one item is required for dispensing.")

    with transaction.atomic():
        dispense = Dispense.objects.create(
            branch=branch,
            patient=patient,
            reference=reference,
            dispensed_by=dispensed_by,
        )

        for line in item_lines:
            item = line["item"]
            quantity = line["quantity"]
            unit_price = line.get("unit_price")
            dispense_item_fifo(
                dispense=dispense,
                item=item,
                quantity=quantity,
                unit_price=unit_price,
                dispensed_by=dispensed_by,
                reference=reference,
            )

        dispense.refresh_total_amount()
        return dispense
