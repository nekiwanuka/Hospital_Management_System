from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.billing.models import Invoice, InvoiceLineItem
from apps.branches.models import Branch
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.radiology.models import ImagingRequest
from apps.reports.views import _build_gross_profit


class GrossProfitReportTests(TestCase):
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
        self.director = user_model.objects.create_user(
            username="director_report",
            password="Passw0rd!",
            role="director",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=self.director,
            module_name="reports",
            can_view=True,
            can_update=True,
        )
        self.patient = Patient.objects.create(
            branch=self.branch,
            first_name="Amina",
            last_name="Nabirye",
            gender="F",
            date_of_birth=date(1995, 5, 12),
            phone="+256700000100",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone="+256700000200",
        )

    def test_build_gross_profit_groups_by_day_branch_and_department(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-GROSS-001",
            patient=self.patient,
            services="Radiology - Chest X-ray",
            total_amount=Decimal("60000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.director,
        )
        InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="radiology",
            description="Radiology - Chest X-ray",
            amount=Decimal("60000.00"),
            total_cost=Decimal("15000.00"),
            profit_amount=Decimal("45000.00"),
            source_model="radiology",
            source_id=1,
        )

        headers, rows = _build_gross_profit(
            self.director,
            invoice.date.date(),
            invoice.date.date(),
        )

        self.assertEqual(
            headers,
            [
                "date",
                "branch",
                "department",
                "service_type",
                "transactions",
                "sales",
                "cost",
                "profit",
            ],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["branch"], "Main Branch")
        self.assertEqual(rows[0]["department"], "radiology")
        self.assertEqual(rows[0]["profit"], Decimal("45000.00"))

    def test_build_gross_profit_can_filter_by_branch_and_department(self):
        second_branch = Branch.objects.create(
            branch_name="Annex Branch",
            branch_code="ANNEX",
            address="Plot 2 Kampala Road",
            city="Kampala",
            country="Uganda",
            phone="+256700000003",
            email="annex@hms.local",
            status="active",
        )
        second_patient = Patient.objects.create(
            branch=second_branch,
            first_name="Joel",
            last_name="Ssemanda",
            gender="M",
            date_of_birth=date(1992, 7, 7),
            phone="+256700000300",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone="+256700000301",
        )

        main_invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-GROSS-002",
            patient=self.patient,
            services="Lab - Urinalysis",
            total_amount=Decimal("30000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.director,
        )
        InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=main_invoice,
            service_type="lab",
            description="Lab - Urinalysis",
            amount=Decimal("30000.00"),
            total_cost=Decimal("10000.00"),
            profit_amount=Decimal("20000.00"),
            source_model="lab",
            source_id=2,
        )

        annex_invoice = Invoice.objects.create(
            branch=second_branch,
            invoice_number="INV-GROSS-003",
            patient=second_patient,
            services="Pharmacy - Panadol",
            total_amount=Decimal("12000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.director,
        )
        InvoiceLineItem.objects.create(
            branch=second_branch,
            invoice=annex_invoice,
            service_type="pharmacy",
            description="Pharmacy - Panadol",
            amount=Decimal("12000.00"),
            total_cost=Decimal("5000.00"),
            profit_amount=Decimal("7000.00"),
            source_model="pharmacy",
            source_id=3,
        )

        _, rows = _build_gross_profit(
            self.director,
            main_invoice.date.date(),
            annex_invoice.date.date(),
            branch_id=self.branch.pk,
            department="laboratory",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["branch"], "Main Branch")
        self.assertEqual(rows[0]["department"], "laboratory")
        self.assertEqual(rows[0]["profit"], Decimal("20000.00"))

    def test_laboratory_profitability_page_lists_fee_cost_and_profit(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-REPORT-LAB-001",
            patient=self.patient,
            services="Lab Test - Urinalysis",
            total_amount=Decimal("30000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.director,
        )
        lab_request = LabRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            requested_by=self.director,
            test_type="Urinalysis",
            status="completed",
            total_cost_snapshot=Decimal("10000.00"),
            profit_amount=Decimal("20000.00"),
        )
        InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="lab",
            description="Lab Test - Urinalysis",
            amount=Decimal("30000.00"),
            total_cost=Decimal("10000.00"),
            profit_amount=Decimal("20000.00"),
            source_model="lab",
            source_id=lab_request.pk,
        )

        self.client.force_login(self.director)
        response = self.client.get(reverse("reports:laboratory_profitability"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Laboratory Profitability")
        self.assertContains(response, "Amina Nabirye")
        self.assertContains(response, "Urinalysis")
        self.assertContains(response, "INV-REPORT-LAB-001")
        self.assertContains(response, "20,000.00")

    def test_radiology_profitability_page_lists_fee_cost_and_profit(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-REPORT-RAD-001",
            patient=self.patient,
            services="Radiology - Chest X-ray",
            total_amount=Decimal("60000.00"),
            payment_method="cash",
            payment_status="paid",
            cashier=self.director,
        )
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            requested_by=self.director,
            imaging_type="xray",
            requested_department="Consultation",
            specific_examination="chest_xray",
            status="completed",
            total_cost_snapshot=Decimal("15000.00"),
            profit_amount=Decimal("45000.00"),
        )
        InvoiceLineItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            service_type="radiology",
            description="Radiology - Chest X-ray",
            amount=Decimal("60000.00"),
            total_cost=Decimal("15000.00"),
            profit_amount=Decimal("45000.00"),
            source_model="radiology",
            source_id=imaging_request.pk,
        )

        self.client.force_login(self.director)
        response = self.client.get(reverse("reports:radiology_profitability"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Radiology Profitability")
        self.assertContains(response, "Chest X-ray")
        self.assertContains(response, "X-Ray")
        self.assertContains(response, "INV-REPORT-RAD-001")
        self.assertContains(response, "45,000.00")
