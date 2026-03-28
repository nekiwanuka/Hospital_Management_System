from django.db import models
from apps.core.models import BranchScopedModel


class Patient(BranchScopedModel):
    GENDER_CHOICES = [("M", "Male"), ("F", "Female"), ("O", "Other")]

    patient_id = models.CharField(max_length=24, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    date_of_birth = models.DateField()
    phone = models.CharField(max_length=30)
    address = models.TextField()
    next_of_kin = models.CharField(max_length=120)
    next_of_kin_phone = models.CharField(max_length=30)
    blood_group = models.CharField(max_length=10, blank=True)
    allergies = models.TextField(blank=True)
    date_registered = models.DateTimeField(auto_now_add=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [models.Index(fields=["branch", "last_name", "first_name"])]

    def __str__(self):
        return f"{self.patient_id} - {self.first_name} {self.last_name}"

    def _generate_patient_id(self):
        branch_code = (
            self.branch.branch_code if self.branch_id and self.branch else "GEN"
        )[:6]
        prefix = f"{branch_code}-PT-"
        last = (
            Patient.objects.filter(patient_id__startswith=prefix)
            .order_by("-patient_id")
            .values_list("patient_id", flat=True)
            .first()
        )
        next_num = 1
        if last:
            try:
                next_num = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                next_num = 1
        return f"{prefix}{next_num:06d}"

    def save(self, *args, **kwargs):
        if not self.patient_id:
            self.patient_id = self._generate_patient_id()
        super().save(*args, **kwargs)
