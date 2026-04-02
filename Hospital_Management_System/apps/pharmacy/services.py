from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.inventory.models import Batch, Item, StockMovement
from apps.pharmacy.models import Medicine


def _active_batches(item):
    return Batch.objects.filter(
        branch=item.branch,
        item=item,
        quantity_remaining__gt=0,
    ).order_by("exp_date", "date_received", "id")


def _sellable_batches(item):
    return _active_batches(item).filter(exp_date__gte=timezone.localdate())


def sellable_quantity_for_item(item):
    return _sellable_batches(item).aggregate(
        total=Coalesce(Sum("quantity_remaining"), 0)
    )["total"]


def _snapshot_batch_for_item(item):
    return _sellable_batches(item).first() or _active_batches(item).first()


def sync_medicine_catalog_for_item(item):
    if not item:
        return None
    if getattr(item, "store_department", "pharmacy") != "pharmacy":
        Medicine.objects.filter(branch=item.branch, inventory_item=item).delete()
        return None

    # Store items should not have their own Medicine record when a
    # corresponding department item already exists.
    if not getattr(item, "is_department_stock", False):
        has_dept_copy = Item.objects.filter(
            branch=item.branch,
            item_name=item.item_name,
            strength=item.strength,
            brand=item.brand,
            store_department="pharmacy",
            is_department_stock=True,
        ).exists()
        if has_dept_copy:
            Medicine.objects.filter(branch=item.branch, inventory_item=item).delete()
            return None

    batch = _snapshot_batch_for_item(item)
    defaults = {
        "name": item.item_name,
        "category": item.category.name,
        "manufacturer": item.brand.manufacturer or item.brand.name,
        "batch_number": batch.batch_number if batch else "",
        "expiry_date": batch.exp_date if batch else timezone.localdate(),
        "purchase_price": (
            batch.unit_cost.quantize(Decimal("0.01")) if batch else Decimal("0.00")
        ),
        "selling_price": batch.selling_price_per_unit if batch else Decimal("0.00"),
        "stock_quantity": sellable_quantity_for_item(item),
    }
    medicine, _ = Medicine.objects.update_or_create(
        branch=item.branch,
        inventory_item=item,
        defaults=defaults,
    )
    return medicine


def sync_branch_medicine_catalog(branch):
    if not branch:
        return

    Medicine.objects.filter(branch=branch).exclude(inventory_item__isnull=True).exclude(
        inventory_item__store_department="pharmacy"
    ).delete()

    item_ids = (
        Item.objects.filter(
            branch=branch,
            store_department="pharmacy",
            batches__isnull=False,
        )
        .distinct()
        .values_list("id", flat=True)
    )
    for item in Item.objects.filter(pk__in=item_ids).select_related(
        "category", "brand"
    ):
        sync_medicine_catalog_for_item(item)


def allocate_inventory_stock_for_medicine(
    *, medicine, quantity, dispensed_by, reference="", unit_price=None
):
    item = medicine.inventory_item
    if not item:
        raise ValidationError("Selected medicine is not linked to inventory.")
    if quantity <= 0:
        raise ValidationError("Quantity must be positive.")

    chosen_unit_price = (
        unit_price if unit_price is not None else medicine.current_selling_price
    )

    with transaction.atomic():
        batches = list(
            Batch.objects.select_for_update()
            .filter(
                branch=item.branch,
                item=item,
                quantity_remaining__gt=0,
                exp_date__gte=timezone.localdate(),
            )
            .order_by("exp_date", "date_received", "id")
        )
        available = sum(batch.quantity_remaining for batch in batches)
        if available < quantity:
            raise ValidationError(
                {
                    "quantity": f"Only {available} units available in stock.",
                }
            )

        remaining = quantity
        allocations = []
        for batch in batches:
            if remaining <= 0:
                break
            take_qty = min(remaining, batch.quantity_remaining)
            batch.quantity_remaining -= take_qty
            batch.save(update_fields=["quantity_remaining", "updated_at"])
            StockMovement.objects.create(
                branch=item.branch,
                item=item,
                batch=batch,
                movement_type="OUT",
                quantity=take_qty,
                reference=reference or f"Pharmacy dispense of {medicine.name}",
                user=dispensed_by,
            )
            allocations.append(
                {
                    "batch": batch,
                    "item": item,
                    "quantity": take_qty,
                    "unit_cost": batch.unit_cost,
                    "unit_price": chosen_unit_price,
                    "total_cost": (batch.unit_cost * Decimal(take_qty)).quantize(
                        Decimal("0.01")
                    ),
                    "total_amount": (chosen_unit_price * Decimal(take_qty)).quantize(
                        Decimal("0.01")
                    ),
                }
            )
            remaining -= take_qty

    sync_medicine_catalog_for_item(item)
    return allocations


def deduct_inventory_stock_for_medicine(
    *, medicine, quantity, dispensed_by, reference=""
):
    allocate_inventory_stock_for_medicine(
        medicine=medicine,
        quantity=quantity,
        dispensed_by=dispensed_by,
        reference=reference,
    )
    return medicine


def available_medicines_queryset():
    return Medicine.objects.select_related("inventory_item").filter(
        stock_quantity__gt=0
    )
