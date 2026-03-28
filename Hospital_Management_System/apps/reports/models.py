from django.db import models
from apps.core.models import BranchScopedModel


class GeneratedReport(BranchScopedModel):
    EXPORT_FORMAT_CHOICES = [
        ("csv", "CSV"),
        ("pdf", "PDF"),
    ]

    report_type = models.CharField(max_length=100)
    export_format = models.CharField(
        max_length=10, choices=EXPORT_FORMAT_CHOICES, default="csv"
    )
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    file_path = models.CharField(max_length=255, blank=True)

    class Meta(BranchScopedModel.Meta):
        indexes = [
            models.Index(fields=["branch", "report_type", "generated_at"]),
            models.Index(fields=["generated_by", "generated_at"]),
        ]
