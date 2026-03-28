from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.branches.models import Branch
from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    Dispense,
    DispenseItem,
    Item,
    StockMovement,
    Supplier,
)


class Command(BaseCommand):
    help = "Drop old medical stores seed data and load fresh pack/unit-aware seed data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--branch-code",
            default="MAIN",
            help="Branch code to reset and reseed medical stores data for.",
        )

    def _seed_batches(self, branch, user, item, supplier, definitions):
        for idx, config in enumerate(definitions, start=1):
            pack_size = config["pack_size_units"]
            packs_received = config["packs_received"]
            purchase_per_pack = config["purchase_price_per_pack"]
            wholesale_per_pack = config["wholesale_price_per_pack"]
            retail_per_unit = config["retail_price_per_unit"]

            batch = Batch.objects.create(
                branch=branch,
                item=item,
                batch_number=f"{item.item_name[:4].upper()}-{idx:03d}",
                mfg_date=timezone.localdate() - timedelta(days=60),
                exp_date=timezone.localdate() + timedelta(days=360 + idx * 30),
                pack_size_units=pack_size,
                packs_received=packs_received,
                quantity_received=pack_size * packs_received,
                purchase_price_per_pack=purchase_per_pack,
                purchase_price_total=Decimal(packs_received) * purchase_per_pack,
                wholesale_price_per_pack=wholesale_per_pack,
                selling_price_per_unit=retail_per_unit,
                supplier=supplier,
                created_by=user,
            )

            StockMovement.objects.create(
                branch=branch,
                item=item,
                batch=batch,
                movement_type="IN",
                quantity=batch.quantity_received,
                reference="Seed reset stock entry",
                user=user,
            )

    @transaction.atomic
    def handle(self, *args, **options):
        branch_code = options["branch_code"].strip().upper()
        branch = Branch.objects.filter(branch_code=branch_code).first()
        if not branch:
            raise CommandError(f"Branch with code '{branch_code}' does not exist.")

        user_model = get_user_model()
        seed_user = (
            user_model.objects.filter(branch=branch, role="pharmacist")
            .order_by("id")
            .first()
            or user_model.objects.filter(branch=branch, role="system_admin")
            .order_by("id")
            .first()
            or user_model.objects.filter(branch=branch).order_by("id").first()
        )
        if not seed_user:
            raise CommandError(
                "No user found for target branch. Create at least one user before seeding."
            )

        dispenses = Dispense.objects.filter(branch=branch)
        DispenseItem.objects.filter(branch=branch).delete()
        dispenses.delete()
        StockMovement.objects.filter(branch=branch).delete()
        Batch.objects.filter(branch=branch).delete()
        Item.objects.filter(branch=branch).delete()
        Supplier.objects.filter(branch=branch).delete()
        Brand.objects.filter(branch=branch).delete()
        Category.objects.filter(branch=branch).delete()

        analgesics = Category.objects.create(branch=branch, name="Analgesics")
        antibiotics = Category.objects.create(branch=branch, name="Antibiotics")

        acme_brand = Brand.objects.create(
            branch=branch, name="AcmeCare", manufacturer="AcmeCare Ltd", country="UG"
        )
        heal_brand = Brand.objects.create(
            branch=branch, name="HealMax", manufacturer="HealMax Pharma", country="IN"
        )

        supplier = Supplier.objects.create(
            branch=branch,
            name="Prime Medical Supplies",
            contact="+256700101010",
            address="Kampala Industrial Area",
        )

        paracetamol = Item.objects.create(
            branch=branch,
            item_name="Paracetamol",
            generic_name="Acetaminophen",
            category=analgesics,
            brand=acme_brand,
            dosage_form="tablet",
            strength="500mg",
            unit_of_measure="piece",
            pack_size="100",
            barcode="PARA-500",
            reorder_level=300,
            is_active=True,
            default_pack_size_units=100,
        )

        amoxicillin = Item.objects.create(
            branch=branch,
            item_name="Amoxicillin",
            generic_name="Amoxicillin",
            category=antibiotics,
            brand=heal_brand,
            dosage_form="capsule",
            strength="500mg",
            unit_of_measure="piece",
            pack_size="30",
            barcode="AMOX-500",
            reorder_level=120,
            is_active=True,
            default_pack_size_units=30,
        )

        self._seed_batches(
            branch,
            seed_user,
            paracetamol,
            supplier,
            [
                {
                    "pack_size_units": 100,
                    "packs_received": 40,
                    "purchase_price_per_pack": Decimal("10000.00"),
                    "wholesale_price_per_pack": Decimal("11000.00"),
                    "retail_price_per_unit": Decimal("200.00"),
                },
                {
                    "pack_size_units": 100,
                    "packs_received": 20,
                    "purchase_price_per_pack": Decimal("9800.00"),
                    "wholesale_price_per_pack": Decimal("10800.00"),
                    "retail_price_per_unit": Decimal("190.00"),
                },
            ],
        )

        self._seed_batches(
            branch,
            seed_user,
            amoxicillin,
            supplier,
            [
                {
                    "pack_size_units": 30,
                    "packs_received": 25,
                    "purchase_price_per_pack": Decimal("9000.00"),
                    "wholesale_price_per_pack": Decimal("9800.00"),
                    "retail_price_per_unit": Decimal("360.00"),
                },
            ],
        )

        self.stdout.write(self.style.SUCCESS("Medical Stores seed reset completed."))
        self.stdout.write(
            self.style.SUCCESS(f"Branch: {branch.branch_name} ({branch.branch_code})")
        )
        self.stdout.write(
            self.style.SUCCESS("Seed now uses pack and unit pricing rules.")
        )
