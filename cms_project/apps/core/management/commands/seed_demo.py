from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.billing.models import Invoice
from apps.branches.models import Branch
from apps.consultation.models import Consultation
from apps.laboratory.models import LabRequest
from apps.patients.models import Patient
from apps.pharmacy.models import Medicine
from apps.radiology.models import (
    BODY_REGION_BY_EXAMINATION,
    RadiologyType,
    ULTRASOUND_EXAMINATIONS,
    X_RAY_EXAMINATIONS,
)
from apps.settingsapp.models import SystemSettings
from apps.triage.models import TriageRecord


def seed_radiology_catalog(branch):
    for imaging_type, examinations in (
        ("xray", X_RAY_EXAMINATIONS),
        ("ultrasound", ULTRASOUND_EXAMINATIONS),
    ):
        for examination_code, examination_name in examinations:
            RadiologyType.objects.get_or_create(
                branch=branch,
                imaging_type=imaging_type,
                examination_code=examination_code,
                defaults={
                    "examination_name": examination_name,
                    "body_region": BODY_REGION_BY_EXAMINATION.get(
                        examination_code, imaging_type.title()
                    ),
                    "is_active": True,
                },
            )


class Command(BaseCommand):
    help = "Seed demo data for cms_v2 starter modules."

    def handle(self, *args, **options):
        settings_obj, _ = SystemSettings.objects.get_or_create(
            id=1,
            defaults={
                "clinic_name": "HMS Demo Clinic",
                "system_email": "system@hms.local",
                "timezone": "UTC",
                "primary_color": "#125ea8",
                "secondary_color": "#16a085",
                "is_initialized": True,
            },
        )
        if not settings_obj.is_initialized:
            settings_obj.is_initialized = True
            settings_obj.save(update_fields=["is_initialized"])

        branch, _ = Branch.objects.get_or_create(
            branch_code="MAIN",
            defaults={
                "branch_name": "Main Branch",
                "address": "Plot 1 Kampala Road",
                "city": "Kampala",
                "country": "Uganda",
                "phone": "+256700000002",
                "email": "main@hms.local",
                "status": "active",
            },
        )

        for existing_branch in Branch.objects.all().order_by("branch_name"):
            seed_radiology_catalog(existing_branch)

        User = get_user_model()
        users_config = [
            ("director", "director", "director@hms.local"),
            ("sysadmin", "system_admin", "sysadmin@hms.local"),
            ("doctor1", "doctor", "doctor1@hms.local"),
            ("nurse1", "nurse", "nurse1@hms.local"),
            ("triage1", "triage_officer", "triage1@hms.local"),
            ("lab1", "lab_technician", "lab1@hms.local"),
            ("pharm1", "pharmacist", "pharm1@hms.local"),
            ("cashier1", "cashier", "cashier1@hms.local"),
            ("recept1", "receptionist", "recept1@hms.local"),
        ]

        created_users = {}
        for username, role, email in users_config:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    role=role,
                    email=email,
                    branch=branch,
                    is_staff=role in {"director", "system_admin"},
                    is_superuser=role in {"director", "system_admin"},
                )
            else:
                user_typed = cast(Any, user)
                user_typed.role = role
                user_typed.branch = branch
                user_typed.email = email
                user_typed.is_staff = role in {"director", "system_admin"}
                user_typed.is_superuser = role in {"director", "system_admin"}
            user.set_password("Passw0rd!")
            user.save()
            created_users[role] = user

        demo_patients = [
            ("PT-0001", "Amina", "Nabirye", "F"),
            ("PT-0002", "Brian", "Kato", "M"),
            ("PT-0003", "Claire", "Nakato", "F"),
            ("PT-0004", "David", "Ssembatya", "M"),
            ("PT-0005", "Evelyn", "Asiimwe", "F"),
        ]

        patients = []
        for idx, (patient_id, first_name, last_name, gender) in enumerate(
            demo_patients, start=1
        ):
            patient, _ = Patient.objects.get_or_create(
                patient_id=patient_id,
                defaults={
                    "branch": branch,
                    "first_name": first_name,
                    "last_name": last_name,
                    "gender": gender,
                    "date_of_birth": date(1990, 1, 1) + timedelta(days=idx * 100),
                    "phone": f"+2567000001{idx:02d}",
                    "address": "Kampala",
                    "next_of_kin": "Relative Name",
                    "next_of_kin_phone": f"+2567000002{idx:02d}",
                    "blood_group": "O+",
                    "allergies": "",
                },
            )
            patients.append(patient)

        triage_nurse = created_users.get("triage_officer") or created_users.get("nurse")
        doctor = created_users["doctor"]
        cashier = created_users["cashier"]
        lab_user = created_users["lab_technician"]

        for idx, patient in enumerate(patients, start=1):
            visit_number = f"VIS-{date.today().strftime('%Y%m%d')}-{idx:03d}"

            TriageRecord.objects.get_or_create(
                branch=branch,
                patient=patient,
                visit_number=visit_number,
                defaults={
                    "temperature": Decimal("36.8"),
                    "blood_pressure": "120/80",
                    "pulse_rate": 78,
                    "respiratory_rate": 18,
                    "oxygen_level": 98,
                    "weight": Decimal("70.0"),
                    "height": Decimal("170.0"),
                    "symptoms": "Headache and fatigue",
                    "triage_officer": triage_nurse,
                    "outcome": "send_to_doctor",
                },
            )

            Consultation.objects.get_or_create(
                branch=branch,
                patient=patient,
                doctor=doctor,
                defaults={
                    "symptoms": "Headache and fatigue",
                    "diagnosis": "Viral syndrome",
                    "treatment_plan": "Hydration and rest",
                    "prescription": "Paracetamol 500mg",
                    "lab_tests_requested": "CBC",
                },
            )

            LabRequest.objects.get_or_create(
                branch=branch,
                patient=patient,
                requested_by=lab_user,
                test_type="Complete Blood Count",
                defaults={
                    "status": "requested",
                    "sample_collected": False,
                    "results": "",
                    "comments": "",
                },
            )

            Invoice.objects.get_or_create(
                branch=branch,
                invoice_number=f"INV-{date.today().strftime('%Y%m%d')}-{idx:03d}",
                defaults={
                    "patient": patient,
                    "services": "Consultation + Basic Labs",
                    "total_amount": Decimal("75000.00"),
                    "payment_method": "cash",
                    "payment_status": "pending",
                    "cashier": cashier,
                },
            )

        medicines = [
            ("Paracetamol 500mg", "Analgesic", "MediPharm", "BATCH-A01"),
            ("Amoxicillin 500mg", "Antibiotic", "HealLabs", "BATCH-B04"),
            ("Vitamin C 1000mg", "Supplement", "NutriCare", "BATCH-C09"),
        ]
        for idx, (name, category, manufacturer, batch_number) in enumerate(
            medicines, start=1
        ):
            Medicine.objects.get_or_create(
                branch=branch,
                name=name,
                defaults={
                    "category": category,
                    "manufacturer": manufacturer,
                    "batch_number": batch_number,
                    "expiry_date": date.today() + timedelta(days=365 + idx * 30),
                    "purchase_price": Decimal("5000.00"),
                    "selling_price": Decimal("8000.00"),
                    "stock_quantity": 100 + idx * 20,
                },
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write(
            self.style.SUCCESS("Demo user password for all created users: Passw0rd!")
        )
