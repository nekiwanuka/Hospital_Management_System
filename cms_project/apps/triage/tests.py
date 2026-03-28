from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice
from apps.branches.models import Branch
from apps.consultation.models import Consultation
from apps.patients.models import Patient
from apps.permissions.models import UserModulePermission
from apps.triage.models import TriageRecord
from apps.visits.models import Visit


class TriageWorkflowTests(TestCase):
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
        self.triage_officer = user_model.objects.create_user(
            username="triage1",
            password="Passw0rd!",
            role="triage_officer",
            branch=self.branch,
        )
        self.receptionist = user_model.objects.create_user(
            username="recept1",
            password="Passw0rd!",
            role="receptionist",
            branch=self.branch,
        )
        self.cashier = user_model.objects.create_user(
            username="cashier1",
            password="Passw0rd!",
            role="cashier",
            branch=self.branch,
        )
        self.doctor = user_model.objects.create_user(
            username="doctor1",
            password="Passw0rd!",
            role="doctor",
            branch=self.branch,
        )

        UserModulePermission.objects.create(
            user=self.triage_officer,
            module_name="triage",
            can_view=True,
            can_create=True,
        )

        self.patient_paid = self._create_patient("Amina", "Nabirye", "F", 1)
        self.patient_waived = self._create_patient("Brian", "Kato", "M", 2)
        self.patient_pending = self._create_patient("Claire", "Nakato", "F", 3)

        self.paid_visit = self._create_visit(self.patient_paid, 1)
        self.waived_visit = self._create_visit(self.patient_waived, 2)
        self.pending_visit = self._create_visit(self.patient_pending, 3)

        Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-TRIAGE-001",
            patient=self.patient_paid,
            visit=self.paid_visit,
            services="Registration",
            total_amount="5000.00",
            payment_method="cash",
            payment_status="paid",
            cashier=self.cashier,
        )

        consultation = Consultation.objects.create(
            branch=self.branch,
            patient=self.patient_waived,
            visit=self.waived_visit,
            doctor=self.doctor,
            symptoms="Review symptoms",
            diagnosis="Stable",
            treatment_plan="Continue medication",
            prescription="",
            follow_up_date=timezone.localdate() + timedelta(days=2),
        )
        Consultation.objects.filter(pk=consultation.pk).update(
            created_at=self.waived_visit.check_in_time - timedelta(minutes=10)
        )

        Invoice.objects.create(
            branch=self.branch,
            invoice_number="INV-TRIAGE-002",
            patient=self.patient_pending,
            visit=self.pending_visit,
            services="Registration",
            total_amount="5000.00",
            payment_method="cash",
            payment_status="pending",
            cashier=self.cashier,
        )

    def _create_patient(self, first_name, last_name, gender, idx):
        return Patient.objects.create(
            branch=self.branch,
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=timezone.localdate() - timedelta(days=10000 + idx),
            phone=f"+256700100{idx:02d}",
            address="Kampala",
            next_of_kin="Relative Name",
            next_of_kin_phone=f"+256701200{idx:02d}",
            blood_group="O+",
            allergies="",
        )

    def _create_visit(self, patient, idx):
        visit = Visit.objects.create(
            branch=self.branch,
            patient=patient,
            visit_type="outpatient",
            status="waiting_triage",
            created_by=self.receptionist,
        )
        Visit.objects.filter(pk=visit.pk).update(
            check_in_time=timezone.now() - timedelta(hours=idx)
        )
        visit.refresh_from_db()
        return visit

    def test_triage_form_shows_only_paid_or_privileged_visits(self):
        self.client.force_login(self.triage_officer)

        response = self.client.get(reverse("triage:create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="id_patient"')
        self.assertContains(response, self.paid_visit.visit_number)
        self.assertContains(response, self.waived_visit.visit_number)
        self.assertNotContains(response, self.pending_visit.visit_number)

    def test_triage_index_shows_only_eligible_queue_entries(self):
        self.client.force_login(self.triage_officer)

        response = self.client.get(reverse("triage:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.patient_paid.first_name)
        self.assertContains(response, self.patient_waived.first_name)
        self.assertNotContains(response, self.patient_pending.first_name)
        self.assertContains(response, "Start Triage")

    def test_triage_record_uses_patient_from_selected_visit(self):
        self.client.force_login(self.triage_officer)

        response = self.client.post(
            reverse("triage:create"),
            {
                "visit": self.paid_visit.pk,
                "temperature": "36.7",
                "blood_pressure": "120/80",
                "pulse_rate": 76,
                "respiratory_rate": 18,
                "oxygen_level": 98,
                "weight": "70.5",
                "height": "170.0",
                "symptoms": "Headache",
                "outcome": "send_to_doctor",
            },
        )

        self.assertRedirects(response, reverse("triage:index"))
        record = TriageRecord.objects.get()
        self.assertEqual(record.visit, self.paid_visit)
        self.assertEqual(record.patient, self.paid_visit.patient)
        self.paid_visit.refresh_from_db()
        self.assertEqual(self.paid_visit.status, "waiting_doctor")
