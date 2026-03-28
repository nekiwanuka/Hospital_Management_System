import re
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.billing.models import FinancialSequenceAnomaly, Invoice
from apps.branches.models import Branch


class Command(BaseCommand):
    help = "Detect daily financial sequence anomalies for invoices and receipts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Date to evaluate in YYYY-MM-DD format. Defaults to today.",
        )

    def handle(self, *args, **options):
        target_date = self._resolve_target_date(options.get("date"))

        deleted = FinancialSequenceAnomaly.objects.filter(
            anomaly_date=target_date,
            detected_by="sequence-check-command",
        ).delete()[0]
        self.stdout.write(
            self.style.NOTICE(f"Cleared {deleted} prior anomalies for {target_date}.")
        )

        branch_ids = (
            Invoice.objects.filter(date__date=target_date)
            .values_list("branch_id", flat=True)
            .distinct()
        )
        created = 0
        for branch in Branch.objects.filter(id__in=branch_ids):
            created += self._check_invoice_sequences(branch, target_date)
            created += self._check_receipt_sequences(branch, target_date)

        self.stdout.write(
            self.style.SUCCESS(
                f"Sequence anomaly scan complete for {target_date}. Created {created} anomalies."
            )
        )

    def _resolve_target_date(self, date_arg):
        if not date_arg:
            return timezone.localdate()
        try:
            return datetime.strptime(date_arg, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Invalid --date value. Use YYYY-MM-DD.") from exc

    def _extract_numeric_token(self, document_number):
        if not document_number:
            return None
        match = re.search(r"(\d+)$", document_number)
        if not match:
            return None
        return int(match.group(1))

    def _record_anomaly(
        self,
        *,
        branch,
        target_date,
        anomaly_type,
        object_type,
        severity,
        message,
        reference_value,
    ):
        FinancialSequenceAnomaly.objects.create(
            branch=branch,
            anomaly_date=target_date,
            anomaly_type=anomaly_type,
            object_type=object_type,
            severity=severity,
            message=message,
            reference_value=reference_value,
            is_resolved=False,
            detected_by="sequence-check-command",
        )

    def _check_invoice_sequences(self, branch, target_date):
        created = 0
        invoice_qs = Invoice.objects.filter(
            branch=branch, date__date=target_date
        ).order_by("date", "id")

        duplicates = {}
        for invoice in invoice_qs:
            duplicates.setdefault(invoice.invoice_number, 0)
            duplicates[invoice.invoice_number] += 1

            if not str(invoice.invoice_number).startswith("INV-"):
                self._record_anomaly(
                    branch=branch,
                    target_date=target_date,
                    anomaly_type="invalid_format",
                    object_type="invoice",
                    severity="high",
                    message="Invoice number does not follow INV- prefix format.",
                    reference_value=invoice.invoice_number,
                )
                created += 1

        for number, count in duplicates.items():
            if count > 1:
                self._record_anomaly(
                    branch=branch,
                    target_date=target_date,
                    anomaly_type="duplicate_sequence",
                    object_type="invoice",
                    severity="high",
                    message=f"Duplicate invoice number detected ({count} occurrences).",
                    reference_value=number,
                )
                created += 1

        last_token = None
        for invoice in invoice_qs:
            token = self._extract_numeric_token(invoice.invoice_number)
            if token is None:
                continue
            if last_token is not None and token < last_token:
                self._record_anomaly(
                    branch=branch,
                    target_date=target_date,
                    anomaly_type="missing_sequence",
                    object_type="invoice",
                    severity="medium",
                    message="Invoice sequence token moved backwards when ordered by creation time.",
                    reference_value=invoice.invoice_number,
                )
                created += 1
            last_token = token

        return created

    def _check_receipt_sequences(self, branch, target_date):
        created = 0
        receipt_qs = Invoice.objects.filter(
            branch=branch,
            date__date=target_date,
            payment_status="paid",
        ).order_by("date", "id")

        duplicates = {}
        for invoice in receipt_qs:
            duplicates.setdefault(invoice.invoice_number, 0)
            duplicates[invoice.invoice_number] += 1

        for number, count in duplicates.items():
            if count > 1:
                self._record_anomaly(
                    branch=branch,
                    target_date=target_date,
                    anomaly_type="duplicate_sequence",
                    object_type="receipt",
                    severity="high",
                    message=f"Duplicate receipt reference detected ({count} occurrences).",
                    reference_value=number,
                )
                created += 1

        return created
