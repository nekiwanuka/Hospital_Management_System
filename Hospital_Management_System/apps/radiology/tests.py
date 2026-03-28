import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

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
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.pharmacy.models import MedicalStoreRequest
from apps.radiology.models import (
    ImagingRequest,
    ImagingResult,
    RadiologyNotification,
    RadiologyQueue,
    RadiologyType,
)
from apps.visits.models import Visit


class RadiologyWorkflowTests(TestCase):
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
            username="doctor1",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )
        self.radiologist = user_model.objects.create_user(
            username="radiologist1",
            password="Passw0rd!",
            role="radiologist",
            branch=self.branch,
        )
        self.technician = user_model.objects.create_user(
            username="radtech1",
            password="Passw0rd!",
            role="radiology_technician",
            branch=self.branch,
        )
        self.cashier = user_model.objects.create_user(
            username="cashier1",
            password="Passw0rd!",
            role="cashier",
            branch=self.branch,
        )
        self.super_admin = user_model.objects.create_user(
            username="admin",
            password="Passw0rd!",
            role="receptionist",
            branch=self.branch,
            is_superuser=True,
            is_staff=True,
        )

        UserModulePermission.objects.create(
            user=self.doctor,
            module_name="radiology",
            can_create=True,
            can_update=False,
        )
        UserModulePermission.objects.create(
            user=self.radiologist,
            module_name="radiology",
            can_view=True,
            can_update=True,
        )
        UserModulePermission.objects.create(
            user=self.technician,
            module_name="radiology",
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
        self.visit = Visit.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit_type="outpatient",
            status="waiting_doctor",
            assigned_clinician=self.doctor,
            created_by=self.doctor,
        )
        self.catalog_item = RadiologyType.objects.create(
            branch=self.branch,
            imaging_type="xray",
            examination_code="chest_xray",
            examination_name="Chest X-ray",
            body_region="Chest",
            is_active=True,
        )
        category = Category.objects.create(branch=self.branch, name="Radiology")
        brand = Brand.objects.create(branch=self.branch, name="Imaging Brand")
        supplier = Supplier.objects.create(branch=self.branch, name="Imaging Supplier")
        self.store_item = Item.objects.create(
            branch=self.branch,
            item_name="X-Ray Film",
            category=category,
            brand=brand,
            dosage_form="other",
            unit_of_measure="Sheet",
            store_department="xray",
            reorder_level=2,
            is_active=True,
        )
        self.ultrasound_store_item = Item.objects.create(
            branch=self.branch,
            item_name="Ultrasound Gel",
            category=category,
            brand=brand,
            dosage_form="other",
            unit_of_measure="Bottle",
            store_department="ultrasound",
            reorder_level=2,
            is_active=True,
        )
        Batch.objects.create(
            branch=self.branch,
            item=self.store_item,
            batch_number="RAD-001",
            exp_date=date.today() + timedelta(days=90),
            pack_size_units=1,
            packs_received=10,
            quantity_received=10,
            purchase_price_per_pack=Decimal("5000.00"),
            purchase_price_total=Decimal("50000.00"),
            wholesale_price_per_pack=Decimal("6000.00"),
            selling_price_per_unit=Decimal("7000.00"),
            supplier=supplier,
            created_by=self.technician,
        )
        Batch.objects.create(
            branch=self.branch,
            item=self.ultrasound_store_item,
            batch_number="RAD-US-001",
            exp_date=date.today() + timedelta(days=90),
            pack_size_units=1,
            packs_received=10,
            quantity_received=10,
            purchase_price_per_pack=Decimal("4000.00"),
            purchase_price_total=Decimal("40000.00"),
            wholesale_price_per_pack=Decimal("5000.00"),
            selling_price_per_unit=Decimal("6000.00"),
            supplier=supplier,
            created_by=self.technician,
        )

    def _mark_visit_paid(self):
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-TEST-001",
            patient=self.patient,
            visit=self.visit,
            services="Radiology",
            total_amount="60000.00",
            payment_method="cash",
            payment_status="paid",
            cashier=self.cashier,
        )
        for req in ImagingRequest.objects.filter(visit=self.visit):
            InvoiceLineItem.objects.get_or_create(
                source_model="radiology",
                source_id=req.pk,
                defaults={
                    "invoice": invoice,
                    "branch": self.branch,
                    "service_type": "radiology",
                    "description": f"Radiology - {req.get_imaging_type_display()}",
                    "amount": invoice.total_amount,
                },
            )

    def _record_consumables(self, imaging_request, quantity=1):
        selected_item = self.store_item
        if imaging_request.imaging_type == "ultrasound":
            selected_item = self.ultrasound_store_item
        return self.client.post(
            reverse("radiology:record_consumables", args=[imaging_request.pk]),
            {
                "form-TOTAL_FORMS": "4",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-item": str(selected_item.pk),
                "form-0-quantity": str(quantity),
                "form-1-item": "",
                "form-1-quantity": "",
                "form-2-item": "",
                "form-2-quantity": "",
                "form-3-item": "",
                "form-3-quantity": "",
            },
        )

    def test_workflow_transition_marks_completed_and_notifies_requesting_doctor(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="requested",
        )
        self._mark_visit_paid()

        self.client.force_login(self.technician)
        self._record_consumables(imaging_request)
        for action in ["schedule", "patient_arrived", "start_scan", "mark_completed"]:
            response = self.client.post(
                reverse("radiology:update_workflow", args=[imaging_request.pk, action])
            )
            self.assertEqual(response.status_code, 302)

        imaging_request.refresh_from_db()
        queue_entry = RadiologyQueue.objects.get(imaging_request=imaging_request)
        self.assertEqual(imaging_request.status, "completed")
        self.assertEqual(queue_entry.status, "completed")
        self.assertIsNotNone(queue_entry.scheduled_for)
        self.assertIsNotNone(queue_entry.patient_arrived_at)
        self.assertIsNotNone(queue_entry.scan_started_at)
        self.assertIsNotNone(queue_entry.completed_at)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "waiting_doctor")
        self.assertTrue(
            RadiologyNotification.objects.filter(
                imaging_request=imaging_request,
                recipient=self.doctor,
                event_type="scan_completed",
            ).exists()
        )

    def test_xray_unit_page_shows_waiting_cards_and_capture_findings_action(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="requested",
        )
        self._mark_visit_paid()

        self.client.force_login(self.technician)
        response = self.client.get(reverse("radiology:xray"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Waiting X-Ray Scan")
        self.assertContains(response, "Waiting X-Ray Report")
        self.assertContains(response, "Capture X-Ray Findings")
        self.assertContains(response, imaging_request.request_identifier)

    def test_detail_page_shows_open_report_recording_form_for_paid_case(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="requested",
        )
        self._mark_visit_paid()

        self.client.force_login(self.technician)
        response = self.client.get(
            reverse("radiology:detail", args=[imaging_request.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Record Consumables Used")
        self.assertContains(response, "Open Report Recording Form")

    def test_superuser_can_see_report_recording_actions_on_detail_page(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="requested",
        )
        self._mark_visit_paid()

        self.client.force_login(self.super_admin)
        response = self.client.get(
            reverse("radiology:detail", args=[imaging_request.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Record Consumables Used")
        self.assertContains(response, "Open Report Recording Form")

    def test_report_upload_notifies_doctor_and_inbox_can_mark_notification_read(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="reporting",
        )
        self._mark_visit_paid()

        self.client.force_login(self.radiologist)
        self._record_consumables(imaging_request)
        response = self.client.post(
            reverse("radiology:upload_result", args=[imaging_request.pk]),
            {
                "technician": "",
                "radiologist": "",
                "machine_used": "Siemens AX-200",
                "examination": "",
                "clinical_information": "",
                "report": "Mild left lower lobe opacity.",
                "findings": "Left basal airspace opacity.",
                "impression": "Early pneumonia.",
                "recommendation": "Correlate clinically.",
                "date_performed": "",
                "date_reported": "",
                "action": "notify_doctor",
            },
        )

        self.assertRedirects(
            response, reverse("radiology:detail", args=[imaging_request.pk])
        )
        imaging_request.refresh_from_db()
        result = ImagingResult.objects.get(imaging_request=imaging_request)
        self.assertEqual(imaging_request.status, "reporting")
        self.assertEqual(result.radiologist, self.radiologist)
        self.assertEqual(result.examination, "Chest X-ray")
        self.assertIsNotNone(result.notified_requesting_doctor_at)

        notification = RadiologyNotification.objects.get(
            imaging_request=imaging_request,
            recipient=self.doctor,
            event_type="report_uploaded",
        )
        self.assertFalse(notification.is_read)

        self.client.force_login(self.doctor)
        inbox_response = self.client.get(reverse("radiology:notification_inbox"))
        self.assertContains(inbox_response, imaging_request.request_identifier)
        self.assertContains(inbox_response, "Unread")

        mark_response = self.client.post(
            reverse("radiology:mark_notification_read", args=[notification.pk]),
            {"next": reverse("radiology:notification_inbox")},
        )
        self.assertRedirects(mark_response, reverse("radiology:notification_inbox"))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_result_form_shows_staff_responsibility_guidance_for_unit(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="ultrasound",
            requested_department="Consultation",
            priority="normal",
            specific_examination="abdominal_ultrasound",
            status="scanning",
        )
        self._mark_visit_paid()

        self.client.force_login(self.radiologist)
        self._record_consumables(imaging_request)
        response = self.client.get(
            reverse("radiology:upload_result", args=[imaging_request.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ultrasound Findings Entry Form")
        self.assertContains(response, "Sonographer / Technician")
        self.assertContains(response, "Radiologist / Reporting Clinician")

    def test_scan_workflow_blocks_until_consumables_are_recorded_and_updates_profit(
        self,
    ):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="scheduled",
        )
        self._mark_visit_paid()

        self.client.force_login(self.technician)
        blocked_response = self.client.post(
            reverse(
                "radiology:update_workflow", args=[imaging_request.pk, "start_scan"]
            )
        )
        self.assertRedirects(
            blocked_response,
            reverse("radiology:record_consumables", args=[imaging_request.pk]),
        )

        capture_response = self._record_consumables(imaging_request)
        self.assertRedirects(
            capture_response,
            reverse("radiology:detail", args=[imaging_request.pk]),
        )

        line_item = InvoiceLineItem.objects.get(
            source_model="radiology",
            source_id=imaging_request.pk,
        )
        line_item.refresh_from_db()
        imaging_request.refresh_from_db()
        self.store_item.refresh_from_db()
        self.assertEqual(str(line_item.total_cost), "5000.00")
        self.assertEqual(str(line_item.profit_amount), "55000.00")
        self.assertIsNotNone(line_item.stock_deducted_at)
        self.assertEqual(str(imaging_request.total_cost_snapshot), "5000.00")
        self.assertEqual(str(imaging_request.profit_amount), "55000.00")
        self.assertEqual(self.store_item.quantity_on_hand, 9)

        allowed_response = self.client.post(
            reverse(
                "radiology:update_workflow", args=[imaging_request.pk, "start_scan"]
            )
        )
        self.assertEqual(allowed_response.status_code, 302)
        imaging_request.refresh_from_db()
        self.assertEqual(imaging_request.status, "scanning")

    def test_radiology_stock_request_uses_radiology_store(self):
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("radiology:request_medical_store_stock"),
            {
                "item": self.store_item.pk,
                "quantity_requested": 4,
                "notes": "Need extra film for the trauma queue.",
            },
        )

        self.assertRedirects(response, reverse("radiology:index"))
        request_record = MedicalStoreRequest.objects.get(item=self.store_item)
        self.assertEqual(request_record.requested_for, "radiology")
        self.assertEqual(request_record.quantity_requested, 4)

    def test_xray_stock_request_tags_request_unit(self):
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("radiology:request_xray_stock"),
            {
                "item": self.store_item.pk,
                "quantity_requested": 2,
                "notes": "X-ray room needs more film.",
            },
        )

        self.assertRedirects(response, reverse("radiology:xray"))
        request_record = MedicalStoreRequest.objects.get(quantity_requested=2)
        self.assertEqual(request_record.requested_for, "radiology")
        self.assertEqual(request_record.requested_unit, "xray")

    def test_ultrasound_stock_request_tags_request_unit(self):
        self.client.force_login(self.technician)

        response = self.client.post(
            reverse("radiology:request_ultrasound_stock"),
            {
                "item": self.ultrasound_store_item.pk,
                "quantity_requested": 1,
                "notes": "Ultrasound room needs contrast accessories.",
            },
        )

        self.assertRedirects(response, reverse("radiology:ultrasound"))
        request_record = MedicalStoreRequest.objects.get(quantity_requested=1)
        self.assertEqual(request_record.requested_for, "radiology")
        self.assertEqual(request_record.requested_unit, "ultrasound")

    def test_supervisor_can_reverse_radiology_consumables_and_restore_stock(self):
        imaging_request = ImagingRequest.objects.create(
            branch=self.branch,
            patient=self.patient,
            visit=self.visit,
            requested_by=self.doctor,
            imaging_type="xray",
            requested_department="Consultation",
            priority="normal",
            specific_examination="chest_xray",
            status="scheduled",
        )
        self._mark_visit_paid()

        self.client.force_login(self.technician)
        capture_response = self._record_consumables(imaging_request)
        self.assertRedirects(
            capture_response,
            reverse("radiology:detail", args=[imaging_request.pk]),
        )

        director = get_user_model().objects.create_user(
            username="raddirector",
            password="Passw0rd!",
            role="director",
            branch=self.branch,
        )
        UserModulePermission.objects.create(
            user=director,
            module_name="radiology",
            can_view=True,
            can_update=True,
        )

        self.client.force_login(director)
        response = self.client.post(
            reverse("radiology:correct_consumables", args=[imaging_request.pk]),
            {"reason": "Wrong film size selected."},
        )

        self.assertRedirects(
            response,
            reverse("radiology:record_consumables", args=[imaging_request.pk]),
        )
        line_item = InvoiceLineItem.objects.get(
            source_model="radiology",
            source_id=imaging_request.pk,
        )
        self.store_item.refresh_from_db()
        imaging_request.refresh_from_db()
        consumption = ServiceConsumption.objects.get(
            branch=self.branch,
            source_model="radiology",
            source_id=imaging_request.pk,
        )
        self.assertIsNotNone(consumption.reversed_at)
        self.assertEqual(consumption.reversal_reason, "Wrong film size selected.")
        self.assertEqual(self.store_item.quantity_on_hand, 10)
        self.assertEqual(str(line_item.total_cost), "0.00")
        self.assertEqual(str(imaging_request.total_cost_snapshot), "0.00")

    def test_dashboard_redirects_technician_to_assigned_xray_queue(self):
        self.technician.radiology_unit_assignment = "xray"
        self.technician.save(update_fields=["radiology_unit_assignment"])

        self.client.force_login(self.technician)
        response = self.client.get(reverse("core:dashboard"))

        self.assertRedirects(response, reverse("radiology:xray"))

    def test_seed_demo_populates_branch_radiology_catalog(self):
        RadiologyType.objects.all().delete()

        call_command("seed_demo")

        self.assertTrue(
            RadiologyType.objects.filter(
                branch__branch_code="MAIN",
                imaging_type="xray",
                examination_code="chest_xray",
            ).exists()
        )
        self.assertTrue(
            RadiologyType.objects.filter(
                branch__branch_code="MAIN",
                imaging_type="ultrasound",
                examination_code="obstetric_ultrasound",
            ).exists()
        )


class RadiologyMigrationBackfillTests(TestCase):
    def test_populate_imaging_request_metadata_backfills_identifier_status_priority_and_body_region(
        self,
    ):
        branch = Branch.objects.create(
            branch_name="Branch Two",
            branch_code="BRTWO",
            address="Plot 2 Kampala Road",
            city="Kampala",
            country="Uganda",
            phone="+256700000003",
            email="branch2@hms.local",
            status="active",
        )
        user_model = get_user_model()
        doctor = user_model.objects.create_user(
            username="doctor2",
            password="Passw0rd!",
            role="doctor",
            branch=branch,
        )
        patient = Patient.objects.create(
            branch=branch,
            first_name="Brian",
            last_name="Kato",
            gender="M",
            date_of_birth=date(1990, 1, 1),
            phone="+256700000101",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone="+256700000201",
        )
        imaging_request = ImagingRequest.objects.create(
            branch=branch,
            patient=patient,
            requested_by=doctor,
            imaging_type="xray",
            requested_department="Consultation",
            specific_examination="pelvic_ultrasound",
            status="requested",
            priority="normal",
        )
        ImagingRequest.objects.filter(pk=imaging_request.pk).update(
            request_identifier="",
            status="reported",
            priority="stat",
            body_region="",
        )

        migration_module = importlib.import_module(
            "apps.radiology.migrations.0003_radiologycomparison_radiologyimage_and_more"
        )
        migration_module.populate_imaging_request_metadata(
            type(
                "Apps",
                (),
                {
                    "get_model": staticmethod(
                        lambda app_label, model_name: ImagingRequest
                    )
                },
            )(),
            None,
        )

        imaging_request.refresh_from_db()
        self.assertEqual(
            imaging_request.request_identifier,
            f"BR{branch.pk}-RAD-{imaging_request.pk:06d}",
        )
        self.assertEqual(imaging_request.status, "completed")
        self.assertEqual(imaging_request.priority, "urgent")
        self.assertEqual(imaging_request.body_region, "Pelvis")
