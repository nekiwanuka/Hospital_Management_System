from datetime import timedelta
from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone


def backfill_legacy_stock_items(apps, schema_editor):
    Item = apps.get_model("inventory", "Item")
    Batch = apps.get_model("inventory", "Batch")
    Brand = apps.get_model("inventory", "Brand")
    Category = apps.get_model("inventory", "Category")
    StockItem = apps.get_model("inventory", "StockItem")
    User = apps.get_model("accounts", "User")

    today = timezone.localdate()

    for stock_item in StockItem.objects.filter(is_active=True).order_by(
        "branch_id", "id"
    ):
        category_name = (stock_item.category or "General").strip() or "General"
        category, _ = Category.objects.get_or_create(
            branch_id=stock_item.branch_id,
            name=category_name,
        )
        brand, _ = Brand.objects.get_or_create(
            branch_id=stock_item.branch_id,
            name="Legacy Inventory Migration",
            defaults={
                "manufacturer": "Legacy Inventory",
                "country": "",
            },
        )

        service_type = stock_item.service_type or ""
        service_code = (stock_item.service_code or "").strip().lower().replace(" ", "_")

        item = (
            Item.objects.filter(
                branch_id=stock_item.branch_id,
                item_name=stock_item.item_name,
                service_type=service_type,
                service_code=service_code,
            )
            .order_by("id")
            .first()
        )
        if not item:
            item = Item.objects.create(
                branch_id=stock_item.branch_id,
                item_name=stock_item.item_name,
                generic_name="",
                category=category,
                brand=brand,
                dosage_form="other",
                strength="",
                unit_of_measure="Unit",
                pack_size="1",
                barcode="",
                service_type=service_type,
                service_code=service_code,
                reorder_level=stock_item.reorder_level,
                description=f"Migrated from legacy inventory department: {stock_item.department}",
                is_active=stock_item.is_active,
                default_pack_size_units=1,
            )
        else:
            updated = False
            if item.service_type != service_type:
                item.service_type = service_type
                updated = True
            if item.service_code != service_code:
                item.service_code = service_code
                updated = True
            if item.reorder_level != stock_item.reorder_level:
                item.reorder_level = stock_item.reorder_level
                updated = True
            if updated:
                item.save(
                    update_fields=[
                        "service_type",
                        "service_code",
                        "reorder_level",
                        "updated_at",
                    ]
                )

        if stock_item.quantity <= 0:
            continue

        batch_number = f"LEGACY-{stock_item.pk}"
        if Batch.objects.filter(
            branch_id=stock_item.branch_id, item=item, batch_number=batch_number
        ).exists():
            continue

        created_by = (
            User.objects.filter(branch_id=stock_item.branch_id).order_by("id").first()
        )
        if created_by is None:
            continue

        unit_cost = stock_item.stock_rate or stock_item.unit_price or Decimal("0.01")
        if unit_cost <= 0:
            unit_cost = Decimal("0.01")
        selling_price = stock_item.unit_price or stock_item.charge_rate or unit_cost
        if selling_price < unit_cost:
            selling_price = unit_cost

        exp_date = (
            stock_item.expiry_date
            if stock_item.expiry_date and stock_item.expiry_date > today
            else today + timedelta(days=3650)
        )

        Batch.objects.create(
            branch_id=stock_item.branch_id,
            item=item,
            batch_number=batch_number,
            exp_date=exp_date,
            pack_size_units=1,
            packs_received=stock_item.quantity,
            quantity_received=stock_item.quantity,
            purchase_price_per_pack=unit_cost,
            purchase_price_total=unit_cost * stock_item.quantity,
            wholesale_price_per_pack=unit_cost,
            selling_price_per_unit=selling_price,
            supplier=None,
            barcode="",
            weight="",
            volume="",
            created_by=created_by,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_batch_pack_size_units_batch_packs_received_and_more"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="service_code",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="item",
            name="service_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Not billable item"),
                    ("lab", "Laboratory Service"),
                    ("radiology", "Radiology Service"),
                    ("consultation", "Consultation"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["branch", "service_type", "service_code"],
                name="inventory_i_branch__6992af_idx",
            ),
        ),
        migrations.RunPython(backfill_legacy_stock_items, migrations.RunPython.noop),
    ]
