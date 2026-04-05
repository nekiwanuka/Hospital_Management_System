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


# ── Seed catalogue ─────────────────────────────────────────────
CATEGORIES = [
    "Analgesics",
    "Antibiotics",
    "Antifungals",
    "Antimalarials",
    "Antihistamines",
    "Antihypertensives",
    "Antidiabetics",
    "Vitamins & Supplements",
    "GI Medications",
    "Respiratory",
    "IV Fluids & Infusions",
    "Surgical Supplies",
    "Lab Reagents",
]

BRANDS = [
    ("AcmeCare", "AcmeCare Ltd", "UG"),
    ("HealMax", "HealMax Pharma", "IN"),
    ("CiplaQCIL", "Cipla Quality Chemicals", "UG"),
    ("GSK", "GlaxoSmithKline", "UK"),
    ("Roche", "Roche Diagnostics", "CH"),
]

SUPPLIERS = [
    ("Prime Medical Supplies", "+256700101010", "Kampala Industrial Area"),
    ("National Medical Stores", "+256414340854", "Entebbe, Uganda"),
]

# (item_name, generic_name, category_index, brand_index, dosage_form, strength,
#  unit, pack_size, store_dept, barcode, reorder, batches_config)
# batches_config: list of (pack_size_units, packs, purchase/pack, wholesale/pack, retail/unit)
ITEMS = [
    (
        "Paracetamol 500mg",
        "Acetaminophen",
        0,
        0,
        "tablet",
        "500mg",
        "piece",
        "100",
        "pharmacy",
        "PARA-500",
        300,
        [(100, 40, "10000", "11000", "200"), (100, 20, "9800", "10800", "190")],
    ),
    (
        "Amoxicillin 500mg",
        "Amoxicillin",
        1,
        1,
        "capsule",
        "500mg",
        "piece",
        "30",
        "pharmacy",
        "AMOX-500",
        120,
        [(30, 25, "9000", "9800", "360")],
    ),
    (
        "Ibuprofen 400mg",
        "Ibuprofen",
        0,
        0,
        "tablet",
        "400mg",
        "piece",
        "100",
        "pharmacy",
        "IBUP-400",
        200,
        [(100, 30, "8000", "9000", "150")],
    ),
    (
        "Metformin 500mg",
        "Metformin HCl",
        6,
        2,
        "tablet",
        "500mg",
        "piece",
        "60",
        "pharmacy",
        "METF-500",
        100,
        [(60, 20, "7200", "8000", "180")],
    ),
    (
        "Amlodipine 5mg",
        "Amlodipine Besylate",
        5,
        3,
        "tablet",
        "5mg",
        "piece",
        "30",
        "pharmacy",
        "AMLO-005",
        90,
        [(30, 30, "4500", "5200", "220")],
    ),
    (
        "Ciprofloxacin 500mg",
        "Ciprofloxacin",
        1,
        2,
        "tablet",
        "500mg",
        "piece",
        "20",
        "pharmacy",
        "CIPR-500",
        80,
        [(20, 25, "6000", "6800", "400")],
    ),
    (
        "Artemether/Lumefantrine",
        "Coartem",
        3,
        2,
        "tablet",
        "20/120mg",
        "piece",
        "24",
        "pharmacy",
        "CRTM-024",
        150,
        [(24, 40, "4800", "5500", "280")],
    ),
    (
        "Cetirizine 10mg",
        "Cetirizine HCl",
        4,
        3,
        "tablet",
        "10mg",
        "piece",
        "30",
        "pharmacy",
        "CETZ-010",
        60,
        [(30, 20, "2700", "3200", "140")],
    ),
    (
        "Omeprazole 20mg",
        "Omeprazole",
        8,
        1,
        "capsule",
        "20mg",
        "piece",
        "30",
        "pharmacy",
        "OMEP-020",
        100,
        [(30, 25, "3600", "4200", "200")],
    ),
    (
        "Salbutamol Inhaler",
        "Salbutamol",
        9,
        3,
        "inhaler",
        "100mcg",
        "piece",
        "1",
        "pharmacy",
        "SALB-INH",
        30,
        [(1, 50, "8500", "9500", "12000")],
    ),
    (
        "Fluconazole 150mg",
        "Fluconazole",
        2,
        2,
        "capsule",
        "150mg",
        "piece",
        "4",
        "pharmacy",
        "FLUC-150",
        40,
        [(4, 30, "3200", "3800", "1200")],
    ),
    (
        "Diclofenac Gel 1%",
        "Diclofenac",
        0,
        0,
        "gel",
        "1%",
        "tube",
        "1",
        "pharmacy",
        "DICL-GEL",
        20,
        [(1, 40, "3500", "4200", "5000")],
    ),
    (
        "ORS Sachets",
        "Oral Rehydration Salts",
        8,
        0,
        "powder",
        "20.5g",
        "sachet",
        "100",
        "pharmacy",
        "ORSS-100",
        200,
        [(100, 15, "5000", "5800", "80")],
    ),
    (
        "Vitamin C 1000mg",
        "Ascorbic Acid",
        7,
        1,
        "tablet",
        "1000mg",
        "piece",
        "60",
        "pharmacy",
        "VITC-100",
        100,
        [(60, 20, "4200", "5000", "120")],
    ),
    (
        "Multivitamin Syrup",
        "Multivitamins",
        7,
        0,
        "syrup",
        "100ml",
        "bottle",
        "1",
        "pharmacy",
        "MULT-SYR",
        30,
        [(1, 40, "6000", "7200", "8500")],
    ),
    (
        "Normal Saline 500ml",
        "Sodium Chloride 0.9%",
        10,
        2,
        "solution",
        "0.9%",
        "bottle",
        "1",
        "pharmacy",
        "NS05-500",
        50,
        [(1, 60, "3000", "3600", "4500")],
    ),
    (
        "Dextrose 5% 500ml",
        "Dextrose",
        10,
        2,
        "solution",
        "5%",
        "bottle",
        "1",
        "pharmacy",
        "DX05-500",
        50,
        [(1, 60, "3200", "3800", "4800")],
    ),
    (
        "Ringers Lactate 500ml",
        "Ringer Lactate",
        10,
        2,
        "solution",
        "500ml",
        "bottle",
        "1",
        "pharmacy",
        "RING-500",
        50,
        [(1, 50, "3500", "4000", "5000")],
    ),
    (
        "Surgical Gloves (M)",
        "Latex Gloves",
        11,
        0,
        "consumable",
        "Medium",
        "pair",
        "100",
        "general",
        "GLVM-100",
        200,
        [(100, 20, "25000", "28000", "350")],
    ),
    (
        "Gauze Rolls",
        "Cotton Gauze",
        11,
        0,
        "consumable",
        "4x4",
        "roll",
        "12",
        "general",
        "GAUZ-012",
        50,
        [(12, 30, "7200", "8400", "800")],
    ),
]


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

        # Clean existing data
        dispenses = Dispense.objects.filter(branch=branch)
        DispenseItem.objects.filter(branch=branch).delete()
        dispenses.delete()
        StockMovement.objects.filter(branch=branch).delete()
        Batch.objects.filter(branch=branch).delete()
        Item.objects.filter(branch=branch).delete()
        Supplier.objects.filter(branch=branch).delete()
        Brand.objects.filter(branch=branch).delete()
        Category.objects.filter(branch=branch).delete()

        # Create categories
        cats = {}
        for name in CATEGORIES:
            cats[name] = Category.objects.create(branch=branch, name=name)

        # Create brands
        brands = []
        for bname, mfr, country in BRANDS:
            brands.append(
                Brand.objects.create(
                    branch=branch, name=bname, manufacturer=mfr, country=country
                )
            )

        # Create suppliers
        suppliers = []
        for sname, contact, addr in SUPPLIERS:
            suppliers.append(
                Supplier.objects.create(
                    branch=branch, name=sname, contact=contact, address=addr
                )
            )
        default_supplier = suppliers[0]

        # Create items with batches
        count = 0
        cat_list = list(cats.values())
        for row in ITEMS:
            (
                item_name,
                generic,
                cat_idx,
                brand_idx,
                form_,
                strength,
                unit,
                pack_size,
                store,
                barcode,
                reorder,
                batch_defs,
            ) = row

            item = Item.objects.create(
                branch=branch,
                item_name=item_name,
                generic_name=generic,
                category=cat_list[cat_idx],
                brand=brands[brand_idx],
                dosage_form=form_,
                strength=strength,
                unit_of_measure=unit,
                pack_size=pack_size,
                barcode=barcode,
                store_department=store,
                reorder_level=reorder,
                is_active=True,
                default_pack_size_units=int(pack_size) if pack_size.isdigit() else 1,
            )

            all_configs = []
            for bd in batch_defs:
                ps, packs, pp, wp, rp = bd
                all_configs.append(
                    {
                        "pack_size_units": ps,
                        "packs_received": packs,
                        "purchase_price_per_pack": Decimal(pp),
                        "wholesale_price_per_pack": Decimal(wp),
                        "retail_price_per_unit": Decimal(rp),
                    }
                )
            self._seed_batches(
                branch,
                seed_user,
                item,
                default_supplier,
                all_configs,
            )
            count += 1

        self.stdout.write(self.style.SUCCESS("Medical Stores seed reset completed."))
        self.stdout.write(
            self.style.SUCCESS(f"Branch: {branch.branch_name} ({branch.branch_code})")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {count} items with batches across {len(cats)} categories."
            )
        )
