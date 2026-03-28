from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.branches.models import Branch
from apps.core.models import AuditLog
from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    InventoryStoreProfile,
    Item,
    Supplier,
)
from apps.inventory.services import (
    consume_service_stock,
    create_dispense_with_items,
    service_stock_cost,
    store_department_for_service,
)
from apps.patients.models import Patient
from apps.pharmacy.models import MedicalStoreRequest


class MedicalStoresFrameworkTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            branch_name="Main Branch",
            branch_code="MAIN",
            address="Plot 1 Kampala Road",
            city="Kampala",
            country="Uganda",
            phone="+256700000002",
            email="main@hms.local",
            status="active",
        )

        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="pharm_store",
            password="Passw0rd!",
            role="pharmacist",
            branch=self.branch,
        )

        self.category = Category.objects.create(branch=self.branch, name="Analgesics")
        self.brand = Brand.objects.create(
            branch=self.branch,
            name="Panadol",
            manufacturer="GSK",
            country="UK",
        )
        self.supplier = Supplier.objects.create(
            branch=self.branch,
            name="Medi Supplies",
            contact="+256700000300",
            address="Kampala",
        )

        self.item = Item.objects.create(
            branch=self.branch,
            item_name="Panadol",
            generic_name="Paracetamol",
            category=self.category,
            brand=self.brand,
            dosage_form="tablet",
            strength="500mg",
            unit_of_measure="Tablet",
            pack_size="10",
            barcode="PAN-001",
            reorder_level=20,
            description="Pain relief",
            is_active=True,
        )

        self.patient = Patient.objects.create(
            branch=self.branch,
            first_name="Amina",
            last_name="Nabirye",
            gender="F",
            date_of_birth=timezone.localdate() - timedelta(days=10000),
            phone="+256700000100",
            address="Kampala",
            next_of_kin="Relative",
            next_of_kin_phone="+256700000101",
        )

    def test_batch_calculates_unit_cost_and_profit_margin(self):
        batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B001",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=100,
            packs_received=1,
            purchase_price_per_pack=Decimal("10000.00"),
            quantity_received=100,
            purchase_price_total=Decimal("20000.00"),
            wholesale_price_per_pack=Decimal("11000.00"),
            selling_price_per_unit=Decimal("300.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.assertEqual(batch.unit_cost, Decimal("100.0000"))
        self.assertEqual(batch.profit_margin, Decimal("200.00"))
        self.assertEqual(batch.quantity_remaining, 100)

    def test_service_stock_cost_uses_matching_store_department(self):
        wrong_store_item = Item.objects.create(
            branch=self.branch,
            item_name="Urinalysis Kit Wrong Store",
            generic_name="Urinalysis Kit",
            category=self.category,
            brand=self.brand,
            dosage_form="other",
            unit_of_measure="Kit",
            store_department="pharmacy",
            service_type="lab",
            service_code="urinalysis",
            reorder_level=5,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=wrong_store_item,
            batch_number="B-WRONG-STORE",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=1,
            packs_received=1,
            purchase_price_per_pack=Decimal("5000.00"),
            quantity_received=1,
            purchase_price_total=Decimal("5000.00"),
            wholesale_price_per_pack=Decimal("5000.00"),
            selling_price_per_unit=Decimal("6000.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        correct_store_item = Item.objects.create(
            branch=self.branch,
            item_name="Urinalysis Kit",
            generic_name="Urinalysis Kit",
            category=self.category,
            brand=self.brand,
            dosage_form="other",
            unit_of_measure="Kit",
            store_department="laboratory",
            service_type="lab",
            service_code="urinalysis",
            reorder_level=5,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=correct_store_item,
            batch_number="B-LAB-STORE",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=1,
            packs_received=1,
            purchase_price_per_pack=Decimal("10000.00"),
            quantity_received=1,
            purchase_price_total=Decimal("10000.00"),
            wholesale_price_per_pack=Decimal("10000.00"),
            selling_price_per_unit=Decimal("12000.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.assertEqual(
            service_stock_cost(self.branch, "lab", "urinalysis"),
            Decimal("10000.0000"),
        )

    def test_radiology_service_store_mapping_splits_xray_and_ultrasound(self):
        self.assertEqual(
            store_department_for_service("radiology", "chest_xray"),
            "xray",
        )
        self.assertEqual(
            store_department_for_service("radiology", "abdominal_ultrasound"),
            "ultrasound",
        )

    def test_batch_rejects_expired_stock_entry(self):
        with self.assertRaises(ValidationError):
            batch = Batch(
                branch=self.branch,
                item=self.item,
                batch_number="B-EXPIRED",
                exp_date=timezone.localdate() - timedelta(days=1),
                quantity_received=10,
                purchase_price_total=Decimal("1000.00"),
                selling_price_per_unit=Decimal("120.00"),
                supplier=self.supplier,
                created_by=self.user,
            )
            batch.full_clean()

    def test_batch_rejects_selling_price_below_cost(self):
        with self.assertRaises(ValidationError):
            batch = Batch(
                branch=self.branch,
                item=self.item,
                batch_number="B-LOW-SELL",
                exp_date=timezone.localdate() + timedelta(days=90),
                quantity_received=10,
                purchase_price_total=Decimal("2000.00"),
                selling_price_per_unit=Decimal("150.00"),
                supplier=self.supplier,
                created_by=self.user,
            )
            batch.full_clean()

    def test_fifo_dispense_uses_earliest_expiry_batch_first(self):
        early = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-EARLY",
            exp_date=timezone.localdate() + timedelta(days=30),
            quantity_received=5,
            purchase_price_total=Decimal("1000.00"),
            selling_price_per_unit=Decimal("250.00"),
            supplier=self.supplier,
            created_by=self.user,
        )
        late = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-LATE",
            exp_date=timezone.localdate() + timedelta(days=120),
            quantity_received=10,
            purchase_price_total=Decimal("2000.00"),
            selling_price_per_unit=Decimal("260.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        dispense = create_dispense_with_items(
            branch=self.branch,
            patient=self.patient,
            dispensed_by=self.user,
            item_lines=[{"item": self.item, "quantity": 7}],
            reference="RX-1001",
        )

        early.refresh_from_db()
        late.refresh_from_db()
        self.assertEqual(early.quantity_remaining, 0)
        self.assertEqual(late.quantity_remaining, 8)
        self.assertEqual(dispense.items.count(), 2)
        self.assertEqual(dispense.total_amount, Decimal("1770.00"))

    def test_dispense_blocks_expired_batches(self):
        expired = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-PAST",
            exp_date=timezone.localdate() + timedelta(days=10),
            quantity_received=4,
            purchase_price_total=Decimal("800.00"),
            selling_price_per_unit=Decimal("240.00"),
            supplier=self.supplier,
            created_by=self.user,
        )
        # Simulate the batch becoming expired after creation.
        Batch.objects.filter(pk=expired.pk).update(
            exp_date=timezone.localdate() - timedelta(days=1)
        )

        with self.assertRaises(ValidationError):
            create_dispense_with_items(
                branch=self.branch,
                patient=self.patient,
                dispensed_by=self.user,
                item_lines=[{"item": self.item, "quantity": 1}],
                reference="RX-EXP",
            )

    def test_medical_store_dashboard_renders_tables_and_actions(self):
        Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-DASH",
            exp_date=timezone.localdate() + timedelta(days=7),
            quantity_received=5,
            purchase_price_total=Decimal("1000.00"),
            selling_price_per_unit=Decimal("250.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory:medical_store_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Medical Stores Control Center")
        self.assertContains(response, "Low-Stock Items")
        self.assertContains(response, "Expiring Batches")
        self.assertContains(response, "Pharmacy Store")
        self.assertContains(response, "Open Dashboard")
        self.assertContains(response, "Store Release Rule")
        self.assertNotContains(response, "Dispense / Sell")
        self.assertNotContains(response, "Issue Stock")

    def test_inventory_home_redirects_to_medical_store_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("inventory:index"))

        self.assertRedirects(
            response,
            reverse("inventory:medical_store_dashboard_by_store", args=["pharmacy"]),
        )

    def test_legacy_issue_stock_route_redirects_to_medical_store_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("inventory:issue"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertRedirects(response, reverse("inventory:medical_store_dashboard"))
        self.assertContains(
            response,
            "Direct stock issue from legacy inventory items is disabled.",
        )

    def test_medical_store_dashboard_shows_current_active_batch_entries(self):
        Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-NON-EXP-SHOW",
            exp_date=timezone.localdate() + timedelta(days=180),
            pack_size_units=100,
            packs_received=3,
            quantity_received=300,
            purchase_price_per_pack=Decimal("10000.00"),
            purchase_price_total=Decimal("30000.00"),
            wholesale_price_per_pack=Decimal("11000.00"),
            selling_price_per_unit=Decimal("200.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("inventory:medical_store_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Current Store Stock")
        self.assertContains(response, "B-NON-EXP-SHOW")

    def test_medical_store_dashboard_filters_current_stock_table(self):
        other_brand = Brand.objects.create(
            branch=self.branch,
            name="OtherBrand",
        )
        other_supplier = Supplier.objects.create(
            branch=self.branch,
            name="Other Supplier",
        )
        other_item = Item.objects.create(
            branch=self.branch,
            item_name="Ibuprofen",
            generic_name="Ibuprofen",
            category=self.category,
            brand=other_brand,
            dosage_form="tablet",
            strength="400mg",
            unit_of_measure="Tablet",
            reorder_level=10,
            is_active=True,
        )

        Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-TARGET-001",
            exp_date=timezone.localdate() + timedelta(days=180),
            pack_size_units=100,
            packs_received=2,
            quantity_received=200,
            purchase_price_per_pack=Decimal("10000.00"),
            purchase_price_total=Decimal("20000.00"),
            wholesale_price_per_pack=Decimal("11000.00"),
            selling_price_per_unit=Decimal("200.00"),
            supplier=self.supplier,
            created_by=self.user,
        )
        Batch.objects.create(
            branch=self.branch,
            item=other_item,
            batch_number="B-OTHER-001",
            exp_date=timezone.localdate() + timedelta(days=180),
            pack_size_units=30,
            packs_received=3,
            quantity_received=90,
            purchase_price_per_pack=Decimal("9000.00"),
            purchase_price_total=Decimal("27000.00"),
            wholesale_price_per_pack=Decimal("9800.00"),
            selling_price_per_unit=Decimal("360.00"),
            supplier=other_supplier,
            created_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("inventory:medical_store_dashboard"),
            {
                "item": "Panadol",
                "batch": "TARGET",
                "supplier": "Medi",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "B-TARGET-001")
        self.assertNotContains(response, "B-OTHER-001")

    def test_store_dashboard_by_store_filters_fulfillment_queue(self):
        MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Panadol",
            category="Analgesics",
            quantity_requested=2,
            requested_by=self.user,
            requested_for="pharmacy",
        )
        MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Urinalysis Kit",
            category="Reagents",
            quantity_requested=1,
            requested_by=self.user,
            requested_for="laboratory",
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("inventory:medical_store_dashboard_by_store", args=["pharmacy"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pharmacy Store Fulfillment Queue")
        self.assertContains(response, "Panadol")
        self.assertNotContains(response, "Urinalysis Kit")

    def test_store_dashboard_shows_store_manager_and_location(self):
        InventoryStoreProfile.objects.create(
            branch=self.branch,
            store_department="pharmacy",
            manager=self.user,
            location="Block A, Ground Floor",
            notes="Daily controlled-drug reconciliation required.",
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("inventory:medical_store_dashboard_by_store", args=["pharmacy"])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Block A, Ground Floor")
        self.assertContains(response, self.user.username)
        self.assertContains(response, "Daily controlled-drug reconciliation required.")

    def test_store_specific_entry_creates_item_under_selected_store(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("inventory:medical_store_entry_by_store", args=["laboratory"]),
            {
                "item_name": "Urinalysis Strip",
                "generic_name": "Urinalysis Strip",
                "category": self.category.pk,
                "brand": self.brand.pk,
                "dosage_form": "other",
                "strength": "",
                "unit_of_measure": "Strip",
                "pack_size": "50",
                "barcode": "LAB-STRIP-001",
                "service_type": "lab",
                "service_code": "urinalysis_strip",
                "reorder_level": 5,
                "description": "Lab strip stock",
                "batch_number": "LAB-BATCH-001",
                "mfg_date": (timezone.localdate() - timedelta(days=30)).isoformat(),
                "exp_date": (timezone.localdate() + timedelta(days=180)).isoformat(),
                "batch_barcode": "LAB-BATCH-001",
                "weight": "",
                "volume": "",
                "pack_size_units": 50,
                "packs_received": 2,
                "purchase_price_per_pack": "10000.00",
                "wholesale_price_per_pack": "12000.00",
                "retail_price_per_unit": "300.00",
                "supplier": self.supplier.pk,
                "new_supplier_name": "",
                "supplier_contact": "",
                "supplier_address": "",
            },
        )

        self.assertRedirects(
            response,
            reverse("inventory:medical_store_dashboard_by_store", args=["laboratory"]),
        )
        item = Item.objects.get(item_name="Urinalysis Strip")
        self.assertEqual(item.store_department, "laboratory")

    def test_legacy_stock_entry_route_redirects_to_default_store_entry(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("inventory:medical_store_entry"))

        self.assertRedirects(
            response,
            reverse("inventory:medical_store_entry_by_store", args=["pharmacy"]),
        )

    def test_radiology_store_dashboard_can_filter_request_unit(self):
        MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="X-Ray Film",
            category="Radiology",
            quantity_requested=3,
            requested_by=self.user,
            requested_for="radiology",
            requested_unit="xray",
        )
        MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Ultrasound Gel",
            category="Radiology",
            quantity_requested=4,
            requested_by=self.user,
            requested_for="radiology",
            requested_unit="ultrasound",
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("inventory:medical_store_dashboard_by_store", args=["radiology"]),
            {"request_unit": "xray"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Radiology Store Fulfillment Queue")
        self.assertContains(response, "X-Ray Film")
        self.assertNotContains(response, "Ultrasound Gel")

    def test_update_store_request_status_marks_request_approved(self):
        request_record = MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Panadol",
            category="Analgesics",
            quantity_requested=5,
            requested_by=self.user,
            requested_for="pharmacy",
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "inventory:update_store_request_status",
                args=[request_record.pk, "approve"],
            ),
            {
                "remarks": "Stock verified against active batches.",
                "next": reverse(
                    "inventory:medical_store_dashboard_by_store", args=["pharmacy"]
                ),
            },
        )

        self.assertRedirects(
            response,
            reverse("inventory:medical_store_dashboard_by_store", args=["pharmacy"]),
        )
        request_record.refresh_from_db()
        self.assertEqual(request_record.status, "approved")
        self.assertEqual(
            request_record.decision_remarks,
            "Stock verified against active batches.",
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="inventory.store_request.approve",
                object_type="medical_store_request",
                object_id=str(request_record.pk),
            ).exists()
        )

    def test_update_store_request_status_requires_remarks_for_rejection(self):
        request_record = MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Panadol",
            category="Analgesics",
            quantity_requested=5,
            requested_by=self.user,
            requested_for="pharmacy",
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "inventory:update_store_request_status",
                args=[request_record.pk, "reject"],
            ),
            {
                "next": reverse(
                    "inventory:medical_store_dashboard_by_store", args=["pharmacy"]
                )
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record.refresh_from_db()
        self.assertEqual(request_record.status, "pending")
        self.assertContains(response, "Reject remarks are required")

    def test_pack_pricing_formula_matches_required_scenario(self):
        batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-PACK-LOGIC",
            exp_date=timezone.localdate() + timedelta(days=120),
            pack_size_units=100,
            packs_received=5,
            purchase_price_per_pack=Decimal("10000.00"),
            quantity_received=500,
            purchase_price_total=Decimal("50000.00"),
            wholesale_price_per_pack=Decimal("11000.00"),
            selling_price_per_unit=Decimal("200.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.assertEqual(batch.unit_cost, Decimal("100.0000"))
        self.assertEqual(batch.wholesale_unit_price, Decimal("110.00"))
        self.assertEqual(batch.profit_per_unit, Decimal("100.0000"))
        self.assertEqual(batch.profit_per_pack, Decimal("1000.00"))
        self.assertEqual(batch.profit_margin_unit, Decimal("100.00"))
        self.assertEqual(batch.profit_margin_pack, Decimal("10.00"))

    def test_service_stock_cost_and_consumption_use_item_batches(self):
        self.item.store_department = "radiology"
        self.item.service_type = "radiology"
        self.item.service_code = "xray"
        self.item.save(
            update_fields=[
                "store_department",
                "service_type",
                "service_code",
                "updated_at",
            ]
        )

        batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-SERVICE",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=1,
            packs_received=5,
            quantity_received=5,
            purchase_price_per_pack=Decimal("2000.00"),
            purchase_price_total=Decimal("10000.00"),
            wholesale_price_per_pack=Decimal("2200.00"),
            selling_price_per_unit=Decimal("2500.00"),
            supplier=self.supplier,
            created_by=self.user,
        )

        self.assertEqual(
            service_stock_cost(self.branch, "radiology", "xray"),
            Decimal("2000.0000"),
        )

        consume_service_stock(
            self.branch,
            "radiology",
            "xray",
            quantity=2,
            consumed_by=self.user,
        )

        batch.refresh_from_db()
        self.assertEqual(batch.quantity_remaining, 3)
