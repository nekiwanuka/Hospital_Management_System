from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.admission.models import (
    Admission,
    AdmissionDailyCharge,
    Bed,
    NursingNote,
    VitalSign,
    Ward,
)
from apps.billing.models import Invoice, InvoiceLineItem
from apps.branches.models import Branch
from apps.consultation.models import Consultation
from apps.delivery.models import DeliveryRecord, DeliveryNote
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
from apps.visits.models import Visit


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

        # ── Wards & Beds ─────────────────────────────────────────
        nurse = created_users["nurse"]
        ward_defs = [
            ("General Ward", "general", "ordinary", Decimal("50000.00"), "Ground", 10),
            ("Maternity Ward", "maternity", "ordinary", Decimal("80000.00"), "1st", 8),
            ("VIP Ward", "general", "vip", Decimal("150000.00"), "2nd", 4),
            ("VVIP Suite", "private", "vvip", Decimal("300000.00"), "3rd", 2),
            ("ICU", "icu", "ordinary", Decimal("250000.00"), "Ground", 4),
            (
                "Paediatric Ward",
                "paediatric",
                "ordinary",
                Decimal("60000.00"),
                "1st",
                6,
            ),
        ]
        created_wards = {}
        for name, wtype, wcat, rate, floor, cap in ward_defs:
            ward, _ = Ward.objects.get_or_create(
                branch=branch,
                name=name,
                defaults={
                    "ward_type": wtype,
                    "ward_category": wcat,
                    "daily_rate": rate,
                    "floor": floor,
                    "capacity": cap,
                    "is_active": True,
                },
            )
            created_wards[name] = ward
            for b in range(1, cap + 1):
                Bed.objects.get_or_create(
                    ward=ward,
                    bed_number=f"{name[:3].upper()}-{b:02d}",
                    defaults={"branch": branch, "status": "available"},
                )

        self.stdout.write(
            self.style.SUCCESS(f"  Created {len(created_wards)} wards with beds.")
        )

        # ── Visits for admitted / delivery patients ───────────────
        now = timezone.now()

        # Create visits for patients who will be admitted
        admission_visits = []
        for idx, patient in enumerate(patients[:3]):
            visit, _ = Visit.objects.get_or_create(
                branch=branch,
                visit_number=f"VA-{date.today().strftime('%y%m')}-{idx+1:04d}",
                defaults={
                    "patient": patient,
                    "visit_type": "admission",
                    "status": "admitted",
                    "created_by": doctor,
                },
            )
            admission_visits.append(visit)

        # ── Admissions ────────────────────────────────────────────
        gen_ward = created_wards.get("General Ward")
        mat_ward = created_wards.get("Maternity Ward")
        vip_ward = created_wards.get("VIP Ward")

        admission_configs = [
            (patients[0], admission_visits[0], gen_ward, "Malaria – severe", 3),
            (
                patients[1],
                admission_visits[1],
                vip_ward,
                "Post-surgical observation",
                2,
            ),
            (
                patients[2],
                admission_visits[2],
                mat_ward,
                "High-risk pregnancy monitoring",
                1,
            ),
        ]
        created_admissions = []
        for patient, visit, ward, diagnosis, days_ago in admission_configs:
            bed = Bed.objects.filter(ward=ward, status="available").first()
            adm, created = Admission.objects.get_or_create(
                branch=branch,
                patient=patient,
                visit=visit,
                discharge_date__isnull=True,
                defaults={
                    "ward": ward.name,
                    "bed": bed.bed_number if bed else "",
                    "bed_assigned": bed,
                    "ward_obj": ward,
                    "doctor": doctor,
                    "nurse": nurse,
                    "diagnosis": diagnosis,
                },
            )
            if created and bed:
                bed.status = "occupied"
                bed.save(update_fields=["status", "updated_at"])
            # Backdate admission
            if created:
                Admission.objects.filter(pk=adm.pk).update(
                    admission_date=now - timedelta(days=days_ago),
                )
                adm.refresh_from_db()
            created_admissions.append(adm)

        self.stdout.write(
            self.style.SUCCESS(f"  Created {len(created_admissions)} admissions.")
        )

        # ── Daily charges & post-payment invoices for admissions ──
        for adm in created_admissions:
            if not adm.ward_obj or adm.daily_rate <= 0:
                continue
            today = timezone.localdate()
            start_date = adm.admission_date.date()
            current = start_date
            while current <= today:
                AdmissionDailyCharge.objects.get_or_create(
                    admission=adm,
                    charge_date=current,
                    defaults={
                        "branch": branch,
                        "amount": adm.daily_rate,
                        "ward_category": adm.ward_obj.ward_category,
                    },
                )
                current += timedelta(days=1)
            adm.last_billed_date = today
            adm.save(update_fields=["last_billed_date", "updated_at"])

            # Create a post_payment invoice for each admission
            inv_num = f"ADM-{date.today().strftime('%y%m')}-{adm.pk:02d}"
            inv, inv_created = Invoice.objects.get_or_create(
                branch=branch,
                invoice_number=inv_num,
                defaults={
                    "patient": adm.patient,
                    "visit": adm.visit,
                    "services": f"Ward charges – {adm.ward}",
                    "total_amount": Decimal("0.00"),
                    "payment_method": "cash",
                    "payment_status": "post_payment",
                    "cashier": cashier,
                },
            )
            if inv_created:
                total = Decimal("0.00")
                for charge in adm.daily_charges.filter(invoice_line__isnull=True):
                    line = InvoiceLineItem.objects.create(
                        invoice=inv,
                        branch=branch,
                        service_type="admission",
                        description=f"Ward charge ({charge.get_ward_category_display()}) – {charge.charge_date:%d %b %Y}",
                        amount=charge.amount,
                        paid_amount=Decimal("0.00"),
                        payment_status="pending",
                        source_model="admission_daily_charge",
                        source_id=charge.pk,
                    )
                    charge.invoice_line = line
                    charge.save(update_fields=["invoice_line", "updated_at"])
                    total += charge.amount
                inv.total_amount = total
                inv.save(update_fields=["total_amount", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                "  Created daily charges & post-payment invoices for admissions."
            )
        )

        # ── Nursing notes & vitals for admissions ─────────────────
        note_examples = [
            ("general", "Patient resting comfortably, no complaints."),
            ("vitals", "Vitals stable. Temperature normal."),
            ("medication", "Administered IV fluids as prescribed."),
            ("handover", "Night shift handover: patient stable, continue monitoring."),
        ]
        for adm in created_admissions:
            for cat, text in note_examples:
                NursingNote.objects.get_or_create(
                    branch=branch,
                    admission=adm,
                    nurse=nurse,
                    category=cat,
                    note=text,
                )
            VitalSign.objects.get_or_create(
                branch=branch,
                admission=adm,
                recorded_by=nurse,
                defaults={
                    "temperature": Decimal("36.7"),
                    "blood_pressure_systolic": 120,
                    "blood_pressure_diastolic": 78,
                    "pulse_rate": 76,
                    "respiratory_rate": 18,
                    "oxygen_saturation": 97,
                    "notes": "Vitals within normal range.",
                },
            )

        # ── Delivery Records ─────────────────────────────────────
        # Patient 2 (Claire) – post-delivery observation
        # Patient 4 (Evelyn) – in labour
        delivery_patient_post = patients[2]  # Claire – maternity admission
        delivery_patient_labour = patients[4]  # Evelyn

        # Create a visit for Evelyn (delivery)
        del_visit, _ = Visit.objects.get_or_create(
            branch=branch,
            visit_number=f"VD-{date.today().strftime('%y%m')}-0001",
            defaults={
                "patient": delivery_patient_labour,
                "visit_type": "admission",
                "status": "admitted",
                "created_by": doctor,
            },
        )

        # Delivery: Claire – already delivered, in post_delivery observation
        d1, d1_created = DeliveryRecord.objects.get_or_create(
            branch=branch,
            patient=delivery_patient_post,
            status__in=["post_delivery", "delivered"],
            defaults={
                "visit": admission_visits[2] if len(admission_visits) > 2 else None,
                "admission": (
                    created_admissions[2] if len(created_admissions) > 2 else None
                ),
                "status": "post_delivery",
                "delivery_type": "normal",
                "baby_gender": "female",
                "baby_weight_kg": Decimal("3.20"),
                "apgar_score_1min": 8,
                "apgar_score_5min": 9,
                "outcome": "live_birth",
                "gravida": 2,
                "parity": 1,
                "gestational_age_weeks": 39,
                "delivered_by": doctor,
                "midwife": nurse,
                "delivery_datetime": now - timedelta(hours=6),
                "notes": "Normal vaginal delivery, mother and baby doing well.",
            },
        )
        if d1_created:
            DeliveryRecord.objects.filter(pk=d1.pk).update(
                admitted_at=now - timedelta(days=1),
                labour_started_at=now - timedelta(hours=12),
            )
            # Post-delivery notes
            for cat, text in [
                (
                    "observation",
                    "Mother and baby bonding well. Breastfeeding initiated.",
                ),
                ("vitals", "Post-delivery vitals: BP 118/72, Temp 36.5°C, Pulse 74."),
                ("medication", "Administered oxytocin as per protocol."),
            ]:
                DeliveryNote.objects.create(
                    branch=branch,
                    delivery=d1,
                    author=nurse,
                    category=cat,
                    note=text,
                )

            # Create post-payment invoice for delivery
            del_inv_num = f"DEL-{date.today().strftime('%y%m')}-{d1.pk:02d}"
            del_inv, _ = Invoice.objects.get_or_create(
                branch=branch,
                invoice_number=del_inv_num,
                defaults={
                    "patient": delivery_patient_post,
                    "visit": d1.visit,
                    "services": "Delivery services – Normal vaginal delivery",
                    "total_amount": Decimal("350000.00"),
                    "payment_method": "cash",
                    "payment_status": "post_payment",
                    "cashier": cashier,
                },
            )

        # Delivery: Evelyn – currently in labour
        d2, d2_created = DeliveryRecord.objects.get_or_create(
            branch=branch,
            patient=delivery_patient_labour,
            status="in_labour",
            defaults={
                "visit": del_visit,
                "status": "in_labour",
                "delivery_type": "normal",
                "gravida": 1,
                "parity": 0,
                "gestational_age_weeks": 38,
                "delivered_by": doctor,
                "midwife": nurse,
                "notes": "Primigravida, contractions every 5 minutes.",
            },
        )
        if d2_created:
            DeliveryRecord.objects.filter(pk=d2.pk).update(
                admitted_at=now - timedelta(hours=4),
                labour_started_at=now - timedelta(hours=2),
            )
            DeliveryNote.objects.create(
                branch=branch,
                delivery=d2,
                author=nurse,
                category="labour_progress",
                note="Cervix dilated 6cm, contractions regular. Fetal heart rate normal.",
            )

        self.stdout.write(self.style.SUCCESS("  Created delivery records with notes."))

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully."))
        self.stdout.write(
            self.style.SUCCESS("Demo user password for all created users: Passw0rd!")
        )
