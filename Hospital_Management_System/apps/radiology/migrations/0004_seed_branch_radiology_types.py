from django.db import migrations


BODY_REGION_BY_EXAMINATION = {
    "chest_xray": "Chest",
    "skull_xray": "Skull",
    "spine_xray": "Spine",
    "pelvic_xray": "Pelvis",
    "hand_xray": "Hand",
    "leg_xray": "Leg",
    "knee_xray": "Knee",
    "foot_xray": "Foot",
    "abdominal_xray": "Abdomen",
    "abdominal_ultrasound": "Abdomen",
    "pelvic_ultrasound": "Pelvis",
    "obstetric_ultrasound": "Obstetric",
    "kidney_ultrasound": "Kidneys",
    "prostate_ultrasound": "Prostate",
    "breast_ultrasound": "Breast",
    "thyroid_ultrasound": "Thyroid",
    "doppler_ultrasound": "Vascular",
}

X_RAY_EXAMINATIONS = [
    ("chest_xray", "Chest X-ray"),
    ("skull_xray", "Skull X-ray"),
    ("spine_xray", "Spine X-ray"),
    ("pelvic_xray", "Pelvic X-ray"),
    ("hand_xray", "Hand X-ray"),
    ("leg_xray", "Leg X-ray"),
    ("knee_xray", "Knee X-ray"),
    ("foot_xray", "Foot X-ray"),
    ("abdominal_xray", "Abdominal X-ray"),
]

ULTRASOUND_EXAMINATIONS = [
    ("abdominal_ultrasound", "Abdominal ultrasound"),
    ("pelvic_ultrasound", "Pelvic ultrasound"),
    ("obstetric_ultrasound", "Obstetric ultrasound"),
    ("kidney_ultrasound", "Kidney ultrasound"),
    ("prostate_ultrasound", "Prostate ultrasound"),
    ("breast_ultrasound", "Breast ultrasound"),
    ("thyroid_ultrasound", "Thyroid ultrasound"),
    ("doppler_ultrasound", "Doppler ultrasound"),
]


def seed_branch_radiology_types(apps, schema_editor):
    Branch = apps.get_model("branches", "Branch")
    RadiologyType = apps.get_model("radiology", "RadiologyType")

    for branch in Branch.objects.all().order_by("pk"):
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


class Migration(migrations.Migration):

    dependencies = [
        ("radiology", "0003_radiologycomparison_radiologyimage_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_branch_radiology_types, migrations.RunPython.noop),
    ]
