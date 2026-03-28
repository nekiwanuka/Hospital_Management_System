from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.branches.models import Branch
from apps.inventory.models import (
    Batch,
    Brand,
    Category,
    Item,
    ServiceConsumption,
    Supplier,
)
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.pharmacy.models import MedicalStoreRequest
from apps.visits.models import Visit


class LaboratoryStoreRequestTests(TestCase):
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
        self.technician = user_model.objects.create_user(
            username="labtech_store",
            password="Passw0rd!",
            role="lab_technician",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=self.technician,
            module_name="laboratory",
            can_view=True,
            can_update=True,
        )

        category = Category.objects.create(branch=self.branch, name="Reagents")
        brand = Brand.objects.create(branch=self.branch, name="Lab Brand")
        supplier = Supplier.objects.create(branch=self.branch, name="Lab Supplier")
        self.item = Item.objects.create(
            branch=self.branch,
            item_name="Urinalysis Kit",
            category=category,
            brand=brand,
            dosage_form="other",
            unit_of_measure="Unit",
            store_department="laboratory",
            reorder_level=2,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="LAB-001",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=1,
            packs_received=10,
            quantity_received=10,
            purchase_price_per_pack=Decimal("10000.00"),
            purchase_price_total=Decimal("100000.00"),
            wholesale_price_per_pack=Decimal("12000.00"),
            selling_price_per_unit=Decimal("15000.00"),
            supplier=supplier,
            created_by=self.technician,
        )

    def test_lab_stock_request_uses_laboratory_store(self):
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("laboratory:request_medical_store_stock"),
            {
                "item": self.item.pk,
                "quantity_requested": 3,
                "notes": "Need kits for today's urinalysis queue.",
            },
        )

        self.assertRedirects(response, reverse("laboratory:index"))
        request_record = MedicalStoreRequest.objects.get()
        self.assertEqual(request_record.requested_for, "laboratory")
        self.assertEqual(request_record.item, self.item)
        self.assertEqual(request_record.medicine_name, "Urinalysis Kit")


class LaboratoryConsumableCaptureTests(TestCase):
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
        self.doctor = user_model.objects.create_user(
            username="labdoctor",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )
        self.technician = user_model.objects.create_user(
            username="labtech_finance",
            password="Passw0rd!",
            role="lab_technician",
            branch=self.branch,
        )
        self.cashier = user_model.objects.create_user(
            username="labcashier",
            password="Passw0rd!",
            role="cashier",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=self.technician,
            module_name="laboratory",
            can_view=True,
            can_update=True,
        )

        self.patient = Patient.objects.create(
            branch=self.branch,
            first_name="Amina",
            last_name="Nabirye",
            gender="F",
            date_of_birth=timezone.localdate() - timedelta(days=365 * 25),
            phone="+256700000100",
            address="Kampala",
            next_of_kin="Relative",
            next_of_kin_phone="+256700000101",
        )
        self.visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="waiting_doctor",
            assigned_clinician=self.doctor,
            created_by=self.doctor,
        )

        category = Category.objects.create(branch=self.branch, name="Reagents")
        brand = Brand.objects.create(branch=self.branch, name="Lab Brand")
        supplier = Supplier.objects.create(branch=self.branch, name="Lab Supplier")
        self.item = Item.objects.create(
            branch=self.branch,
            item_name="Urinalysis Reagent",
            category=category,
            brand=brand,
            dosage_form="other",
            unit_of_measure="Bottle",
            store_department="laboratory",
            reorder_level=2,
            is_active=True,
        )
        self.batch = Batch.objects.create(
            branch=self.branch,
            item=self.item,
            batch_number="LAB-REAL-COST-001",
            exp_date=timezone.localdate() + timedelta(days=90),
            pack_size_units=1,
            packs_received=10,
            quantity_received=10,
            purchase_price_per_pack=Decimal("10000.00"),
            purchase_price_total=Decimal("100000.00"),
            wholesale_price_per_pack=Decimal("12000.00"),
            selling_price_per_unit=Decimal("15000.00"),
            supplier=supplier,
            created_by=self.technician,
        )
        self.lab_request = LabRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            test_type="Urinalysis",
            status="requested",
        )
        self.invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-LAB-CONSUME-001",
            patient=self.patient,
            visit=self.visit,
            services="Lab Test - Urinalysis",
            total_amount=Decimal("30000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.cashier,
        )
        self.line_item = InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=self.invoice,
            service_type="lab",
            description="Lab Test - Urinalysis",
            amount=Decimal("30000.00"),
            source_model="lab",
            source_id=self.lab_request.pk,
        )

    def _consumable_post_data(self):
        return {
            "form-TOTAL_FORMS": "4",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "form-0-item": str(self.item.pk),
            "form-0-quantity": "1",
            "form-1-item": "",
            "form-1-quantity": "",
            "form-2-item": "",
            "form-2-quantity": "",
            "form-3-item": "",
            "form-3-quantity": "",
        }

    def test_lab_result_entry_requires_consumables_and_updates_profit_from_actual_usage(
        self,
    ):
        self.client.force_login(self.technician)

        blocked_response = self.client.get(
            reverse("laboratory:update_result", args=[self.lab_request.pk])
        )
        self.assertRedirects(
            blocked_response,
            reverse("laboratory:record_consumables", args=[self.lab_request.pk]),
        )

        capture_response = self.client.post(
            reverse("laboratory:record_consumables", args=[self.lab_request.pk]),
            self._consumable_post_data(),
        )
        self.assertRedirects(
            capture_response,
            reverse("laboratory:detail", args=[self.lab_request.pk]),
        )

        self.line_item.refresh_from_db()
        self.lab_request.refresh_from_db()
        self.batch.refresh_from_db()
        self.assertEqual(str(self.line_item.total_cost), "10000.00")
        self.assertEqual(str(self.line_item.profit_amount), "20000.00")
        self.assertIsNotNone(self.line_item.stock_deducted_at)
        self.assertEqual(str(self.lab_request.total_cost_snapshot), "10000.00")
        self.assertEqual(str(self.lab_request.profit_amount), "20000.00")
        self.assertEqual(self.batch.quantity_remaining, 9)

        result_form_response = self.client.get(
            reverse("laboratory:update_result", args=[self.lab_request.pk])
        )
        self.assertEqual(result_form_response.status_code, 200)
        self.assertContains(result_form_response, "Consumables Already Captured")

    def test_supervisor_can_reverse_lab_consumables_and_restore_stock(self):
        self.client.force_login(self.technician)
        capture_response = self.client.post(
            reverse("laboratory:record_consumables", args=[self.lab_request.pk]),
            self._consumable_post_data(),
        )
        self.assertRedirects(
            capture_response,
            reverse("laboratory:detail", args=[self.lab_request.pk]),
        )

        director = get_user_model().objects.create_user(
            username="labdirector",
            password="Passw0rd!",
            role="director",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=director,
            module_name="laboratory",
            can_view=True,
            can_update=True,
        )

        self.client.force_login(director)
        response = self.client.post(
            reverse("laboratory:correct_consumables", args=[self.lab_request.pk]),
            {"reason": "Wrong reagent selected for this patient."},
        )

        self.assertRedirects(
            response,
            reverse("laboratory:record_consumables", args=[self.lab_request.pk]),
        )
        self.batch.refresh_from_db()
        self.line_item.refresh_from_db()
        self.lab_request.refresh_from_db()
        consumption = ServiceConsumption.objects.get(
            branch=self.branch,
            source_model="lab",
            source_id=self.lab_request.pk,
        )
        self.assertIsNotNone(consumption.reversed_at)
        self.assertEqual(
            consumption.reversal_reason, "Wrong reagent selected for this patient."
        )
        self.assertEqual(self.batch.quantity_remaining, 10)
        self.assertEqual(str(self.line_item.total_cost), "0.00")
        self.assertEqual(str(self.line_item.profit_amount), "30000.00")
        self.assertEqual(str(self.lab_request.total_cost_snapshot), "0.00")
