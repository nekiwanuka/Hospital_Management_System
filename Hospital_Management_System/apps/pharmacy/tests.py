from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.branches.models import Branch
from apps.inventory.models import Batch, Brand, Category, Item, Supplier
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.pharmacy.models import (
    DispenseBatchAllocation,
    DispenseRecord,
    MedicalStoreRequest,
    Medicine,
    PharmacyRequest,
)
from apps.pharmacy.services import sync_medicine_catalog_for_item
from apps.visits.models import Visit


class PharmacyInventoryIntegrationTests(TestCase):
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
        self.pharmacist = user_model.objects.create_user(
            username="pharm_inventory",
            password="Passw0rd!",
            role="pharmacist",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=self.pharmacist,
            module_name="pharmacy",
            can_view=True,
            can_create=True,
            can_update=True,
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
            reorder_level=10,
            is_active=True,
        )
        self.batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-PHARM-001",
            exp_date=timezone.localdate() + timedelta(days=120),
            pack_size_units=10,
            packs_received=1,
            quantity_received=10,
            purchase_price_per_pack=Decimal("1000.00"),
            purchase_price_total=Decimal("1000.00"),
            wholesale_price_per_pack=Decimal("1200.00"),
            selling_price_per_unit=Decimal("150.00"),
            supplier=self.supplier,
            created_by=self.pharmacist,
        )
        self.medicine = sync_medicine_catalog_for_item(self.item)

    def test_dispense_uses_inventory_batches_for_linked_medicine(self):
        DispenseRecord.objects.create(
            branch=self.branch,
            patient=self.patient,
            medicine=self.medicine,
            dispensed_by=self.pharmacist,
            quantity=2,
            unit_price="150.00",
        )

        self.batch.refresh_from_db()
        self.medicine.refresh_from_db()
        self.assertEqual(self.batch.quantity_remaining, 8)
        self.assertEqual(self.medicine.stock_quantity, 8)

    def test_dispense_records_batch_level_cost_allocations(self):
        second_batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="B-PHARM-002",
            exp_date=timezone.localdate() + timedelta(days=180),
            pack_size_units=10,
            packs_received=1,
            quantity_received=10,
            purchase_price_per_pack=Decimal("2000.00"),
            purchase_price_total=Decimal("2000.00"),
            wholesale_price_per_pack=Decimal("2300.00"),
            selling_price_per_unit=Decimal("300.00"),
            supplier=self.supplier,
            created_by=self.pharmacist,
        )
        self.medicine = sync_medicine_catalog_for_item(self.item)

        record = DispenseRecord.objects.create(
            branch=self.branch,
            patient=self.patient,
            medicine=self.medicine,
            dispensed_by=self.pharmacist,
            quantity=12,
            unit_price=Decimal("300.00"),
        )

        allocations = list(record.allocations.order_by("batch__batch_number"))
        self.assertEqual(len(allocations), 2)
        self.assertEqual(allocations[0].batch.batch_number, "B-PHARM-001")
        self.assertEqual(allocations[0].quantity, 10)
        self.assertEqual(allocations[1].batch.batch_number, "B-PHARM-002")
        self.assertEqual(allocations[1].quantity, 2)
        self.assertEqual(record.total_cost_snapshot, Decimal("1400.00"))
        self.assertEqual(record.unit_cost_snapshot, Decimal("116.6667"))
        self.assertEqual(record.profit_amount, Decimal("2200.00"))

        self.batch.refresh_from_db()
        second_batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_remaining, 0)
        self.assertEqual(second_batch.quantity_remaining, 8)

    def test_dispense_syncs_billed_request_to_actual_dispense_cost(self):
        visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="waiting_pharmacy",
            created_by=self.pharmacist,
        )
        request_record = PharmacyRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=visit,
            requested_by=self.pharmacist,
            medicine=self.medicine,
            quantity=5,
        )
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-PHARM-REQ-001",
            patient=self.patient,
            visit=visit,
            services="Pharmacy Request - Panadol x5",
            total_amount=Decimal("750.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.pharmacist,
        )
        line_item = InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="pharmacy",
            description="Pharmacy Request - Panadol x5",
            amount=Decimal("750.00"),
            unit_cost=Decimal("0.00"),
            total_cost=Decimal("0.00"),
            profit_amount=Decimal("750.00"),
            source_model="pharmacy_request",
            source_id=request_record.pk,
        )

        self.client.force_login(self.pharmacist)
        response = self.client.post(
            reverse("pharmacy:dispense"),
            {
                "sale_type": DispenseRecord.SALE_TYPE_PRESCRIPTION,
                "visit": visit.pk,
                "patient": self.patient.pk,
                "medicine": self.medicine.pk,
                "quantity": 5,
                "prescribed_by": "",
                "prescription_notes": "",
                "walk_in_name": "",
                "walk_in_phone": "",
            },
        )

        self.assertRedirects(response, reverse("pharmacy:prescriptions"))
        request_record.refresh_from_db()
        line_item.refresh_from_db()
        self.assertEqual(request_record.status, "dispensed")
        self.assertEqual(line_item.unit_cost, Decimal("100.0000"))
        self.assertEqual(line_item.total_cost, Decimal("500.00"))
        self.assertEqual(line_item.profit_amount, Decimal("250.00"))
        self.assertTrue(
            DispenseBatchAllocation.objects.filter(
                dispense_record__visit=visit,
                dispense_record__medicine=self.medicine,
            ).exists()
        )

    def test_fulfilling_internal_request_deducts_source_stock(self):
        request_record = MedicalStoreRequest.objects.create(
            branch=self.branch,
            item=self.item,
            medicine_name="Panadol",
            category="Analgesics",
            quantity_requested=5,
            requested_by=self.pharmacist,
        )

        self.client.force_login(self.pharmacist)
        response = self.client.post(
            reverse("inventory:fulfill_pharmacy_request", args=[request_record.pk]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        request_record.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(request_record.status, "fulfilled")
        # Source store batch should be deducted
        self.assertEqual(self.batch.quantity_remaining, 5)
