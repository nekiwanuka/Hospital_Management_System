from datetime import date, timedelta
from urllib.parse import quote
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.billing.models import CashierShiftSession, Invoice, InvoiceLineItem
from apps.branches.models import Branch
from apps.consultation.models import Consultation
from apps.inventory.models import Batch, Brand, Category, Item
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.pharmacy.models import DispenseRecord, Medicine, PharmacyRequest
from apps.radiology.models import ImagingRequest
from apps.visits.models import Visit
from apps.visits.services import transition_visit


class ConsultationRequestWorkflowTests(TestCase):
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
            username="doctor_consult",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )
        self.cashier = user_model.objects.create_user(
            username="cashier_consult",
            password="Passw0rd!",
            role="cashier",
            branch=self.branch,
        )
        self.pharmacist = user_model.objects.create_user(
            username="pharm_consult",
            password="Passw0rd!",
            role="pharmacist",
            branch=self.branch,
        )
        self.rad_tech = user_model.objects.create_user(
            username="radtech_consult",
            password="Passw0rd!",
            role="radiology_technician",
            branch=self.branch,
        )
        self.system_admin = user_model.objects.create_user(
            username="sysadmin_consult",
            password="Passw0rd!",
            role="system_admin",
            branch=self.branch,
        )
        self.receptionist = user_model.objects.create_user(
            username="recept_consult",
            password="Passw0rd!",
            role="receptionist",
            branch=self.branch,
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

        self.visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="waiting_doctor",
            assigned_clinician=self.doctor,
            created_by=self.receptionist,
        )

        self.medicine = Medicine.objects.create(
            branch=self.branch,
            name="Paracetamol 500mg",
            category="Analgesic",
            manufacturer="MediPharm",
            batch_number="BATCH-A01",
            expiry_date=date.today() + timedelta(days=365),
            purchase_price="5000.00",
            selling_price="8000.00",
            stock_quantity=100,
        )

        radiology_category = Category.objects.create(
            branch=self.branch,
            name="Radiology",
        )
        radiology_brand = Brand.objects.create(
            branch=self.branch,
            name="Legacy Imaging Stock",
        )
        radiology_item = Item.objects.create(
            branch=self.branch,
            item_name="Xray Consumables",
            category=radiology_category,
            brand=radiology_brand,
            dosage_form="other",
            unit_of_measure="Unit",
            service_code="xray",
            service_type="radiology",
            reorder_level=10,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=radiology_item,
            batch_number="XRAY-LEGACY-1",
            exp_date=date.today() + timedelta(days=365),
            pack_size_units=1,
            packs_received=100,
            quantity_received=100,
            purchase_price_per_pack="2000.00",
            purchase_price_total="200000.00",
            wholesale_price_per_pack="2000.00",
            selling_price_per_unit="2000.00",
            created_by=self.system_admin,
        )

    def _create_pending_invoice_for_source(
        self, source_model, source_id, amount="10000.00"
    ):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number=f"INV-{source_model}-{source_id}",
            patient=self.patient,
            visit=self.visit,
            services=f"{source_model} charge",
            total_amount=amount,
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            branch=self.branch,
            service_type=(
                "pharmacy" if source_model.startswith("pharmacy") else "radiology"
            ),
            description=f"{source_model} line",
            amount=amount,
            source_model=source_model,
            source_id=source_id,
        )
        return invoice

    def test_pharmacy_request_billing_dispense_returns_to_doctor_and_badges_update(
        self,
    ):
        self.client.force_login(self.doctor)
        response = self.client.post(
            reverse("consultation:request_pharmacy", args=[self.visit.pk]),
            {
                "medicine": self.medicine.pk,
                "quantity": 2,
                "notes": "Take after meals",
            },
        )
        self.assertEqual(response.status_code, 302)

        pharmacy_request = PharmacyRequest.objects.get(visit=self.visit)
        self.visit.refresh_from_db()
        self.assertEqual(pharmacy_request.status, "requested")
        self.assertEqual(self.visit.status, "billing_queue")

        index_response = self.client.get(reverse("consultation:index"))
        self.assertContains(index_response, "Waiting Pharmacy")

        invoice = self._create_pending_invoice_for_source(
            "pharmacy_request", pharmacy_request.pk, amount="16000.00"
        )

        self.client.force_login(self.cashier)
        CashierShiftSession.objects.create(
            branch=self.branch,
            opened_by=self.cashier,
            opening_float="50000.00",
            status="open",
        )
        pay_response = self.client.post(
            reverse("billing:update_payment", args=[invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "cash",
            },
        )
        self.assertEqual(pay_response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "waiting_pharmacy")

        self.client.force_login(self.pharmacist)
        dispense_response = self.client.post(
            reverse("pharmacy:dispense"),
            {
                "sale_type": "prescription",
                "visit": self.visit.pk,
                "patient": self.patient.pk,
                "medicine": self.medicine.pk,
                "quantity": 2,
                "prescribed_by": self.doctor.pk,
                "prescription_notes": "Take after meals",
            },
        )
        self.assertEqual(dispense_response.status_code, 302)

        pharmacy_request.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(pharmacy_request.status, "dispensed")
        self.assertEqual(self.visit.status, "waiting_doctor")

        self.client.force_login(self.doctor)
        index_after_dispense = self.client.get(reverse("consultation:index"))
        self.assertNotContains(index_after_dispense, "Waiting Pharmacy")

    def test_radiology_request_payment_and_completion_returns_to_doctor_and_badge_clears(
        self,
    ):
        self.client.force_login(self.doctor)
        response = self.client.post(
            reverse("consultation:request_radiology", args=[self.visit.pk]),
            {
                "imaging_type": "xray",
                "priority": "normal",
                "clinical_notes": "Persistent chest pain",
            },
        )
        self.assertEqual(response.status_code, 302)

        imaging_request = ImagingRequest.objects.get(visit=self.visit)
        self.visit.refresh_from_db()
        self.assertEqual(imaging_request.status, "requested")
        self.assertEqual(self.visit.status, "billing_queue")

        waiting_badge_index = self.client.get(reverse("consultation:index"))
        self.assertContains(waiting_badge_index, "Waiting Radiology Results")

        invoice = self._create_pending_invoice_for_source(
            "radiology", imaging_request.pk, amount="50000.00"
        )

        self.client.force_login(self.cashier)
        CashierShiftSession.objects.create(
            branch=self.branch,
            opened_by=self.cashier,
            opening_float="50000.00",
            status="open",
        )
        pay_response = self.client.post(
            reverse("billing:update_payment", args=[invoice.pk]),
            {
                "payment_status": "paid",
                "payment_method": "cash",
            },
        )
        self.assertEqual(pay_response.status_code, 302)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "radiology_requested")

        self.client.force_login(self.rad_tech)
        complete_response = self.client.post(
            reverse(
                "radiology:update_workflow", args=[imaging_request.pk, "mark_completed"]
            )
        )
        self.assertEqual(complete_response.status_code, 302)

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "waiting_doctor")

        self.client.force_login(self.doctor)
        index_after_completion = self.client.get(reverse("consultation:index"))
        self.assertNotContains(index_after_completion, "Waiting Radiology Results")

    def test_billing_create_avoids_double_billing_when_matching_pharmacy_request_exists(
        self,
    ):
        pharmacy_request = PharmacyRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            medicine=self.medicine,
            quantity=1,
            unit_price_snapshot=self.medicine.selling_price,
            status="requested",
        )

        DispenseRecord.objects.create(
            branch=self.branch,
            sale_type=DispenseRecord.SALE_TYPE_PRESCRIPTION,
            patient=self.patient,
            visit=self.visit,
            medicine=self.medicine,
            dispensed_by=self.pharmacist,
            prescribed_by=self.doctor,
            quantity=1,
            unit_price=self.medicine.selling_price,
        )

        self.client.force_login(self.cashier)
        create_response = self.client.post(
            reverse("billing:create"),
            {
                "visit": self.visit.pk,
                "patient": self.patient.pk,
                "payment_method": "cash",
                "payment_status": "pending",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        invoice = (
            Invoice.objects.filter(visit=self.visit).order_by("-created_at").first()
        )
        self.assertIsNotNone(invoice)

        source_models = list(
            invoice.line_items.order_by("id").values_list("source_model", flat=True)
        )
        self.assertIn("pharmacy_request", source_models)
        self.assertNotIn("pharmacy", source_models)
        self.assertEqual(source_models.count("pharmacy_request"), 1)
        self.visit.refresh_from_db()
        self.assertNotEqual(self.visit.status, "completed")

    def test_doctor_schedule_follow_up_does_not_complete_visit(self):
        self.client.force_login(self.doctor)

        follow_up_date = (date.today() + timedelta(days=7)).isoformat()
        response = self.client.post(
            reverse("consultation:start", args=[self.visit.pk]),
            {
                "consultation_room": "Consultation Room 1",
                "symptoms": "Mild headache",
                "diagnosis": "Follow-up required",
                "treatment_plan": "Supportive care",
                "prescription": "Paracetamol",
                "lab_tests_requested": "",
                "follow_up_date": follow_up_date,
            },
        )

        self.assertRedirects(response, reverse("consultation:index"))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "waiting_doctor")
        self.assertIsNone(self.visit.check_out_time)

    def test_doctor_can_mark_visit_complete_explicitly(self):
        self.client.force_login(self.doctor)

        response = self.client.post(
            reverse("consultation:complete_visit", args=[self.visit.pk]),
            {"panel": "active"},
        )

        self.assertRedirects(response, f"{reverse('consultation:index')}?panel=active")
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "completed")
        self.assertIsNotNone(self.visit.check_out_time)

    def test_doctor_can_open_admitted_patient_even_if_assigned_to_another_clinician(
        self,
    ):
        other_doctor = get_user_model().objects.create_user(
            username="doctor_other",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )
        admitted_visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="admission",
            status="admitted",
            assigned_clinician=other_doctor,
            created_by=self.receptionist,
        )

        self.client.force_login(self.doctor)
        response = self.client.get(
            reverse("consultation:start", args=[admitted_visit.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.patient.first_name)

    def test_archive_lists_only_patients_cleared_by_current_doctor(self):
        other_doctor = get_user_model().objects.create_user(
            username="doctor_archive_other",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )
        patient_two = Patient.objects.create(
            branch=self.branch,
            first_name="Brian",
            last_name="Kato",
            gender="M",
            date_of_birth=date(1990, 1, 1),
            phone="+256700000101",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone="+256700000201",
        )

        mine = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="waiting_doctor",
            assigned_clinician=self.doctor,
            created_by=self.receptionist,
        )
        others = Visit.objects.create(
            branch=self.branch,
            patient=patient_two,
            visit_type="outpatient",
            status="waiting_doctor",
            assigned_clinician=other_doctor,
            created_by=self.receptionist,
        )

        transition_visit(mine, "completed", self.doctor)
        transition_visit(others, "completed", other_doctor)

        self.client.force_login(self.doctor)
        response = self.client.get(reverse("consultation:index"))
        self.assertContains(response, "My Cleared Patients Archive")
        self.assertContains(response, mine.visit_number)
        self.assertNotContains(response, others.visit_number)

    def test_consultation_panel_filter_active_hides_archive_and_admitted_sections(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("consultation:index"), {"panel": "active"})
        self.assertContains(response, "My Active Patients")
        self.assertNotContains(response, "My Cleared Patients Archive")
        self.assertNotContains(response, "Admitted Patients (Running Access)")

    def test_consultation_panel_filter_archive_hides_active_and_admitted_sections(self):
        self.client.force_login(self.doctor)
        response = self.client.get(reverse("consultation:index"), {"panel": "archive"})
        self.assertContains(response, "My Cleared Patients Archive")
        self.assertNotContains(response, "My Active Patients")
        self.assertNotContains(response, "Admitted Patients (Running Access)")

    def test_index_links_persist_selected_panel_parameter(self):
        admitted_visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="admission",
            status="admitted",
            assigned_clinician=self.doctor,
            created_by=self.receptionist,
        )

        self.client.force_login(self.doctor)
        response = self.client.get(reverse("consultation:index"), {"panel": "admitted"})
        self.assertContains(
            response,
            f"{reverse('consultation:start_next')}?panel=admitted",
        )
        self.assertContains(
            response,
            f"{reverse('consultation:start', args=[admitted_visit.pk])}?panel=admitted",
        )

    def test_discharge_redirect_keeps_selected_panel(self):
        self.client.force_login(self.doctor)
        response = self.client.post(
            reverse("consultation:discharge_patient", args=[self.visit.pk]),
            {"panel": "archive"},
        )
        self.assertRedirects(
            response,
            f"{reverse('consultation:start', args=[self.visit.pk])}?panel=archive",
        )
        self.visit.refresh_from_db()
        self.assertNotEqual(self.visit.status, "completed")

    def test_doctor_can_only_discharge_admitted_patients(self):
        admitted_visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="admission",
            status="admitted",
            assigned_clinician=self.doctor,
            created_by=self.receptionist,
        )

        self.client.force_login(self.doctor)
        response = self.client.post(
            reverse("consultation:discharge_patient", args=[admitted_visit.pk]),
            {"panel": "admitted"},
        )

        self.assertRedirects(
            response,
            f"{reverse('consultation:index')}?panel=admitted",
        )
        admitted_visit.refresh_from_db()
        self.assertEqual(admitted_visit.status, "completed")
        self.assertIsNotNone(admitted_visit.check_out_time)

    def test_valid_follow_up_for_discharged_patient_skips_consultation_billing(self):
        prior_admission = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="admission",
            status="admitted",
            assigned_clinician=self.doctor,
            created_by=self.receptionist,
        )
        transition_visit(prior_admission, "completed", self.doctor)

        Consultation.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=prior_admission,
            doctor=self.doctor,
            consultation_room="Consultation Room 1",
            symptoms="Recovered",
            diagnosis="Post-discharge review",
            treatment_plan="Return for review",
            follow_up_date=date.today() + timedelta(days=5),
        )

        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse("visits:create"),
            {
                "patient": self.patient.pk,
                "visit_type": "outpatient",
            },
        )

        self.assertEqual(response.status_code, 302)
        new_visit = Visit.objects.order_by("-id").first()
        self.assertIsNotNone(new_visit)
        self.assertEqual(new_visit.status, "waiting_triage")
        self.assertFalse(Invoice.objects.filter(visit=new_visit).exists())

    def test_expired_follow_up_requires_consultation_billing(self):
        Consultation.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            doctor=self.doctor,
            consultation_room="Consultation Room 1",
            symptoms="Stable",
            diagnosis="Routine follow-up",
            treatment_plan="Observe",
            follow_up_date=date.today() - timedelta(days=1),
        )

        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse("visits:create"),
            {
                "patient": self.patient.pk,
                "visit_type": "outpatient",
            },
        )

        self.assertEqual(response.status_code, 302)
        new_visit = Visit.objects.order_by("-id").first()
        self.assertIsNotNone(new_visit)
        self.assertEqual(new_visit.status, "billing_queue")
        self.assertTrue(Invoice.objects.filter(visit=new_visit).exists())

    def test_archive_history_link_carries_return_to_token(self):
        transition_visit(self.visit, "completed", self.doctor)

        self.client.force_login(self.doctor)
        response = self.client.get(reverse("consultation:index"), {"panel": "archive"})
        self.assertContains(
            response,
            f"{reverse('patients:detail', args=[self.patient.pk])}?history_only=1",
        )
        self.assertContains(response, "return_to=")

    def test_history_only_patient_detail_hides_edit_controls_for_doctor(self):
        self.client.force_login(self.doctor)
        response = self.client.get(
            reverse("patients:detail", args=[self.patient.pk]),
            {
                "history_only": "1",
                "return_to": f"{reverse('consultation:index')}?panel=archive",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Initiate Visit")
        self.assertNotContains(response, "bi bi-pencil")
        self.assertContains(
            response, f"href=\"{reverse('consultation:index')}?panel=archive\""
        )

    def test_workbench_radiology_links_include_return_to_token(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            priority="normal",
            clinical_notes="Chest follow-up",
            status="requested",
        )

        self.client.force_login(self.doctor)
        response = self.client.get(
            reverse("consultation:start", args=[self.visit.pk]),
            {"panel": "active"},
        )

        self.assertContains(
            response,
            f"{reverse('radiology:detail', args=[imaging_request.pk])}?return_to=",
        )

    def test_consultation_invoice_link_to_billing_preserves_back_target(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-CONSULT-001",
            patient=self.patient,
            visit=self.visit,
            services="Consultation follow-up",
            total_amount="25000.00",
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )

        self.client.force_login(self.system_admin)
        consultation_url = (
            f"{reverse('consultation:start', args=[self.visit.pk])}?panel=active"
        )
        consultation_response = self.client.get(
            reverse("consultation:start", args=[self.visit.pk]),
            {"panel": "active"},
        )
        self.assertContains(
            consultation_response,
            f"{reverse('billing:detail', args=[invoice.pk])}?return_to=",
        )
        encoded_return_to = quote(consultation_url, safe="/")
        self.assertContains(
            consultation_response,
            f"{reverse('billing:detail', args=[invoice.pk])}?return_to={encoded_return_to}",
        )

        billing_response = self.client.get(
            reverse("billing:detail", args=[invoice.pk]),
            {"return_to": consultation_url},
        )
        self.assertEqual(billing_response.status_code, 200)
        self.assertContains(billing_response, f'href="{consultation_url}"')
