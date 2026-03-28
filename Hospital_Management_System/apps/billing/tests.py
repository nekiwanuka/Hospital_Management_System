from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from apps.billing.models import (
    ApprovalRequest,
    CashDrawer,
    CashierShiftSession,
    Invoice,
)
from apps.billing.models import InvoiceLineItem, InvoiceLinePayment, Receipt
from apps.branches.models import Branch
from apps.core.models import AuditLog
from apps.inventory.models import Batch, Brand, Category, Item, Supplier
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.radiology.models import ImagingRequest
from apps.visits.models import Visit


class BillingVisitFlowTests(TestCase):
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
        self.cashier = user_model.objects.create_user(
            username="cashier1",
            password="Passw0rd!",
            role="cashier",
            branch=self.branch,
        )
        self.receptionist = user_model.objects.create_user(
            username="recept1",
            password="Passw0rd!",
            role="receptionist",
            branch=self.branch,
        )
        self.director = user_model.objects.create_user(
            username="director1",
            password="Passw0rd!",
            role="director",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=self.cashier,
            module_name="billing",
            can_view=True,
            can_update=True,
        )
        UserModulePermission.objects.create(
            user=self.director,
            module_name="billing",
            can_view=True,
            can_update=True,
        )

        self.patient = Patient.objects.create(
            branch=self.branch,
            first_name="Amina",
            last_name="Nabirye",
            gender="F",
            date_of_birth="1995-05-12",
            phone="+256700000100",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone="+256700000200",
        )
        self.visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="billing_queue",
            created_by=self.receptionist,
        )
        self.invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-VISIT-001",
            patient=self.patient,
            visit=self.visit,
            services="Initial consultation registration",
            total_amount="50000.00",
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )
        self.invoice_line = InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=self.invoice,
            service_type="referral",
            description="Initial billing charge",
            amount="50000.00",
            source_model="referral",
            source_id=1,
        )
        self.active_shift = CashierShiftSession.objects.create(
            branch=self.branch,
            opened_by=self.cashier,
            opening_float="50000.00",
            status="open",
        )
        self.category = Category.objects.create(branch=self.branch, name="Diagnostics")
        self.brand = Brand.objects.create(branch=self.branch, name="Generic")
        self.supplier = Supplier.objects.create(
            branch=self.branch, name="Central Supplies"
        )

    def _create_service_item(
        self,
        *,
        item_name,
        store_department,
        service_type,
        service_code,
        batch_number,
        unit_cost,
    ):
        unit_cost = Decimal(str(unit_cost))
        item = Item.objects.create(
            branch=self.branch,
            item_name=item_name,
            generic_name=item_name,
            category=self.category,
            brand=self.brand,
            dosage_form="other",
            unit_of_measure="Kit",
            store_department=store_department,
            service_type=service_type,
            service_code=service_code,
            reorder_level=1,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=item,
            batch_number=batch_number,
            exp_date=timezone.localdate() + timedelta(days=120),
            pack_size_units=1,
            packs_received=1,
            quantity_received=1,
            purchase_price_per_pack=unit_cost,
            purchase_price_total=unit_cost,
            wholesale_price_per_pack=unit_cost,
            selling_price_per_unit=unit_cost + 1,
            supplier=self.supplier,
            created_by=self.cashier,
        )
        return item

    def test_paid_visit_invoice_moves_patient_to_triage(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "cash",
            },
        )

        receipt = Receipt.objects.get(invoice=self.invoice)
        self.assertRedirects(
            response, reverse("billing:receipt_detail", args=[receipt.pk])
        )
        self.visit.refresh_from_db() # type: ignore
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "paid")
        self.assertEqual(self.visit.status, "waiting_triage")

    def test_billing_detail_explains_triage_before_doctor(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("billing:detail", args=[self.invoice.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "After you mark this visit invoice as paid")
        self.assertContains(response, "forwarded to triage first")

    def test_billing_detail_back_link_uses_return_to(self):
        self.client.force_login(self.cashier)

        return_to = f"{reverse('consultation:index')}?panel=workbench"
        response = self.client.get(
            reverse("billing:detail", args=[self.invoice.pk]),
            {"return_to": return_to},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{return_to}"')

    def test_update_payment_redirect_preserves_return_to(self):
        self.client.force_login(self.cashier)

        return_to = f"{reverse('consultation:index')}?panel=workbench"
        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "cash",
                "return_to": return_to,
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('billing:receipt_detail', args=[Receipt.objects.get(invoice=self.invoice).pk])}?return_to=%2Fconsultation%2F%3Fpanel%3Dworkbench",
        )

    def test_invoice_and_quotation_documents_are_viewable(self):
        self.client.force_login(self.cashier)

        invoice_response = self.client.get(
            reverse("billing:invoice_document", args=[self.invoice.pk])
        )
        self.assertEqual(invoice_response.status_code, 200)
        self.assertContains(invoice_response, "INVOICE")
        self.assertContains(invoice_response, "cashier1")

        quotation_response = self.client.get(
            reverse("billing:quotation_document", args=[self.invoice.pk])
        )
        self.assertEqual(quotation_response.status_code, 200)
        self.assertContains(quotation_response, "QUOTATION")
        self.assertContains(quotation_response, "cashier1")

    def test_cashier_cannot_rollback_paid_invoice_status(self):
        self.invoice.payment_status = "paid"
        self.invoice.save(update_fields=["payment_status", "updated_at"])
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "pending",
                "payment_method": "cash",
                "status_reason": "Correction",
            },
        )

        self.assertRedirects(
            response, reverse("billing:detail", args=[self.invoice.pk])
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "paid")
        approval = ApprovalRequest.objects.get(invoice=self.invoice)
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.requested_by, self.cashier)

    def test_director_rollback_submits_approval_request(self):
        self.invoice.payment_status = "paid"
        self.invoice.save(update_fields=["payment_status", "updated_at"])
        self.client.force_login(self.director)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "pending",
                "payment_method": "cash",
                "status_reason": "Charge correction after reconciliation",
            },
        )

        self.assertRedirects(
            response, reverse("billing:detail", args=[self.invoice.pk])
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "paid")
        approval = ApprovalRequest.objects.get(invoice=self.invoice)
        self.assertEqual(approval.status, "pending")
        self.assertEqual(approval.requested_by, self.director)

    def test_director_can_approve_paid_rollback_request(self):
        self.invoice.payment_status = "paid"
        self.invoice.save(update_fields=["payment_status", "updated_at"])

        approval = ApprovalRequest.objects.create(
            branch=self.branch,
            approval_type="paid_rollback",
            invoice=self.invoice,
            requested_by=self.cashier,
            from_status="paid",
            to_status="pending",
            requested_payment_method="cash",
            reason="End-of-day correction",
        )

        self.client.force_login(self.director)
        response = self.client.post(
            reverse("billing:review_approval_request", args=[approval.pk]),
            {"action": "approve", "reviewer_notes": "Approved"},
        )

        self.assertRedirects(response, reverse("billing:approval_requests"))
        self.invoice.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "pending")
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.reviewed_by, self.director)

    def test_billing_financial_events_are_written_to_audit_log(self):
        self.client.force_login(self.cashier)

        self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "cash",
            },
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action="billing.invoice.status_change",
                object_type="invoice",
                object_id=str(self.invoice.pk),
            ).exists()
        )

    def test_partial_payment_updates_balance_and_generates_partial_receipt(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "partial",
                "payment_method": "cash",
                "amount_paid": "10000.00",
            },
        )

        receipt = Receipt.objects.get(invoice=self.invoice)
        self.assertRedirects(
            response, reverse("billing:receipt_detail", args=[receipt.pk])
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "partial")
        self.assertEqual(str(self.invoice.balance_due_amount), "40000.00")
        self.assertEqual(receipt.receipt_type, "partial")
        self.assertEqual(str(receipt.balance_due), "40000.00")

    def test_non_cash_payment_requires_transaction_id(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "mobile_money",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Transaction ID is required for non-cash payments."
        )
        self.assertFalse(Receipt.objects.filter(invoice=self.invoice).exists())

    def test_post_payment_marks_invoice_without_creating_receipt(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:update_payment", args=[self.invoice.pk]),
            {
                "payment_status": "post_payment",
                "payment_method": "cash",
            },
        )

        self.assertRedirects(
            response, reverse("billing:detail", args=[self.invoice.pk])
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payment_status, "post_payment")
        self.assertFalse(Receipt.objects.filter(invoice=self.invoice).exists())

    def test_payment_page_paginates_history_to_three_items(self):
        self.client.force_login(self.cashier)
        drawer = CashDrawer.objects.create(
            branch=self.branch,
            service_type="referral",
            drawer_name="Referral Cashier Point",
        )
        for index in range(4):
            InvoiceLinePayment.objects.create(
                branch=self.branch,
                line_item=self.invoice_line,
                drawer=drawer,
                amount_paid="1000.00",
                payment_method="cash",
                received_by=self.cashier,
            )
            Receipt.objects.create(
                branch=self.branch,
                receipt_number=f"RCPT-{index}",
                invoice=self.invoice,
                patient=self.patient,
                amount_paid="1000.00",
                total_invoice_amount="50000.00",
                balance_due="49000.00",
                payment_method="cash",
                receipt_type="partial",
                received_by=self.cashier,
            )

        response = self.client.get(reverse("billing:detail", args=[self.invoice.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Last 3 transactions per page", count=2)
        self.assertEqual(len(response.context["line_payments"]), 3)
        self.assertEqual(len(response.context["receipt_history"]), 3)

    def test_shift_close_with_high_variance_creates_approval_request(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:close_shift", args=[self.active_shift.pk]),
            {
                "declared_cash_total": "90000.00",
                "variance_reason": "Count mismatch after teller handover",
            },
        )

        self.assertRedirects(response, reverse("billing:index"))
        self.active_shift.refresh_from_db()
        self.assertEqual(self.active_shift.status, "pending_approval")
        self.assertTrue(
            ApprovalRequest.objects.filter(
                approval_type="shift_variance",
                cashier_shift=self.active_shift,
                status="pending",
            ).exists()
        )

    def test_open_shift_uses_branch_configured_variance_threshold(self):
        self.active_shift.status = "closed"
        self.active_shift.closed_at = timezone.now()
        self.active_shift.closed_by = self.cashier
        self.active_shift.save(
            update_fields=["status", "closed_at", "closed_by", "updated_at"]
        )
        self.branch.shift_variance_threshold = "7500.00"
        self.branch.save(update_fields=["shift_variance_threshold", "updated_at"])

        self.client.force_login(self.cashier)
        response = self.client.post(
            reverse("billing:open_shift"),
            {
                "opening_float": "100000.00",
                "shift_notes": "Morning shift",
            },
        )

        self.assertRedirects(response, reverse("billing:index"))
        new_shift = CashierShiftSession.objects.filter(
            branch=self.branch,
            opened_by=self.cashier,
            status="open",
        ).latest("created_at")
        self.assertEqual(str(new_shift.variance_threshold), "7500.00")

    def test_open_shift_blocked_when_branch_has_pending_shift_variance_approval(self):
        self.active_shift.status = "closed"
        self.active_shift.closed_at = timezone.now()
        self.active_shift.closed_by = self.cashier
        self.active_shift.save(
            update_fields=["status", "closed_at", "closed_by", "updated_at"]
        )

        pending_shift = CashierShiftSession.objects.create(
            branch=self.branch,
            opened_by=self.cashier,
            opening_float="40000.00",
            status="pending_approval",
            declared_cash_total="70000.00",
            expected_cash_total="60000.00",
            variance_amount="10000.00",
            variance_threshold="5000.00",
        )
        ApprovalRequest.objects.create(
            branch=self.branch,
            approval_type="shift_variance",
            cashier_shift=pending_shift,
            requested_by=self.cashier,
            reason="Mismatch awaiting director review",
            status="pending",
        )

        self.client.force_login(self.cashier)
        response = self.client.post(
            reverse("billing:open_shift"),
            {
                "opening_float": "10000.00",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Cannot open a new shift while this branch has a pending shift variance approval.",
        )
        self.assertFalse(
            CashierShiftSession.objects.filter(
                branch=self.branch,
                opened_by=self.cashier,
                status="open",
            ).exists()
        )

    def test_paid_lab_invoice_waits_for_technician_consumable_capture(self):
        lab_item = self._create_service_item(
            item_name="Urinalysis Kit",
            store_department="laboratory",
            service_type="lab",
            service_code="urinalysis",
            batch_number="LAB-COST-001",
            unit_cost="10000.00",
        )
        lab_request = LabRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.receptionist,
            test_type="urinalysis",
            status="requested",
        )
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-LAB-COST-001",
            patient=self.patient,
            visit=self.visit,
            services="Lab Test - urinalysis",
            total_amount="30000.00",
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )
        line_item = InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="lab",
            description="Lab Test - urinalysis",
            amount="30000.00",
            unit_cost="0.00",
            total_cost="0.00",
            profit_amount="30000.00",
            source_model="lab",
            source_id=lab_request.pk,
        )

        self.client.force_login(self.director)
        response = self.client.post(
            reverse("billing:update_payment", args=[invoice.pk]),
            {"payment_status": "paid", "payment_method": "cash"},
        )

        receipt = Receipt.objects.get(invoice=invoice)
        self.assertRedirects(
            response, reverse("billing:receipt_detail", args=[receipt.pk])
        )
        line_item.refresh_from_db()
        lab_request.refresh_from_db()
        self.assertEqual(str(line_item.total_cost), "0.00")
        self.assertEqual(str(line_item.profit_amount), "0.00")
        self.assertIsNone(line_item.stock_deducted_at)
        self.assertEqual(str(lab_request.total_cost_snapshot), "0.00")
        self.assertEqual(str(lab_request.profit_amount), "0.00")
        self.assertEqual(lab_item.quantity_on_hand, 1)

    def test_paid_radiology_invoice_waits_for_technician_consumable_capture(self):
        radiology_item = self._create_service_item(
            item_name="Chest X-Ray Consumable",
            store_department="radiology",
            service_type="radiology",
            service_code="chest_xray",
            batch_number="RAD-COST-001",
            unit_cost="15000.00",
        )
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.receptionist,
            imaging_type="xray",
            specific_examination="chest_xray",
            requested_department="Consultation",
            status="requested",
        )
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-RAD-COST-001",
            patient=self.patient,
            visit=self.visit,
            services="Radiology - Chest X-ray",
            total_amount="60000.00",
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )
        line_item = InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="radiology",
            description="Radiology - Chest X-ray",
            amount="60000.00",
            unit_cost="0.00",
            total_cost="0.00",
            profit_amount="60000.00",
            source_model="radiology",
            source_id=imaging_request.pk,
        )

        self.client.force_login(self.director)
        response = self.client.post(
            reverse("billing:update_payment", args=[invoice.pk]),
            {"payment_status": "paid", "payment_method": "cash"},
        )

        receipt = Receipt.objects.get(invoice=invoice)
        self.assertRedirects(
            response, reverse("billing:receipt_detail", args=[receipt.pk])
        )
        line_item.refresh_from_db()
        imaging_request.refresh_from_db()
        self.assertEqual(str(line_item.total_cost), "0.00")
        self.assertEqual(str(line_item.profit_amount), "0.00")
        self.assertIsNone(line_item.stock_deducted_at)
        self.assertEqual(str(imaging_request.total_cost_snapshot), "0.00")
        self.assertEqual(str(imaging_request.profit_amount), "0.00")
        self.assertEqual(radiology_item.quantity_on_hand, 1)

    def test_cashier_cannot_access_billing_without_open_shift(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("billing:detail", args=[self.invoice.pk]), follow=True)

        self.assertRedirects(response, reverse("billing:open_shift"))
        self.assertContains(response, "Opening Float")

    def test_cashier_can_open_shift(self):
        self.client.force_login(self.cashier)

        response = self.client.post(
            reverse("billing:open_shift"),
            {"opening_float": "10000.00"},
            follow=True
        )

        self.assertRedirects(response, reverse("billing:index"))
        self.assertTrue(
            CashierShiftSession.objects.filter(opened_by=self.cashier, status="open").exists()
        )
