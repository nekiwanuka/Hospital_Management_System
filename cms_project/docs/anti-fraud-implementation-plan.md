# HMS Anti-Fraud Implementation Plan

## Objective

Enable CEO-level oversight and reduce financial cheating through hard controls, reconciliation, and tamper-evident operations.

## Phase 1 (Quick Wins: 1-2 Days)

### Controls

1. Restrict paid status rollback (`paid -> pending/partial`) to `director` or `system_admin` only.
2. Require a non-empty reason for every paid status rollback.
3. Record explicit financial audit events (invoice create, status changes, line payments) with before/after details.
4. Remove cashier-facing drawer choice from payment posting to prevent manual routing abuse.
5. Expose printable invoice, receipt, and quotation documents with facility header (logo, name, address/contact) and cashier identity.

### Delivered in current implementation

1. Paid rollback restrictions and reason enforcement in billing status updates.
2. Financial event logging into `core.AuditLog` using action names:
   - `billing.invoice.create`
   - `billing.invoice.status_change`
   - `billing.line_payment.create`
3. Cashier point workflow replacing drawer selection in billing UI.
4. New printable documents:
   - `/billing/<id>/invoice/`
   - `/billing/<id>/receipt/`
   - `/billing/<id>/quotation/`

### Validation checklist

1. Cashier cannot roll back paid invoice.
2. Director/system admin can roll back only with reason.
3. Audit log entries exist for financial events.
4. Invoice, receipt, quotation pages print with branded header and cashier identity.

## Phase 2 (Strong Controls: 1 Week)

### Build targets

1. Approval workflow table for risky actions:
   - paid rollback
   - void
   - refund
   - large discounts
   - end-of-day reopen
2. Shift controls:
   - opening float
   - closing declaration
   - expected vs declared variance
   - mandatory supervisor approval for high variance
3. End-of-day financial lock:
   - closed periods read-only
   - reopen requires approval request and reason
4. Sequence integrity checker:
   - detect missing/duplicate invoice and receipt numbers
   - daily exception report to CEO

### Suggested backlog items

1. Add `finance_approvals` app with models: `ApprovalRequest`, `ApprovalDecision`.
2. Add `cashier_shift` models: `ShiftSession`, `ShiftReconciliation`.
3. Add nightly management command for sequence and reconciliation anomalies.
4. Add CEO exception dashboard card set in core dashboard.

### Delivered in current implementation

1. Added `ApprovalRequest` table in billing with statuses (`pending`, `approved`, `rejected`, `cancelled`) and reviewer metadata.
2. Paid rollback now routes through approval request creation instead of direct status update.
3. Added executive approval screens:
   - `/billing/approvals/`
   - `/billing/approvals/<id>/review/`
4. Added `FinancialSequenceAnomaly` table and daily command:
   - `manage.py check_financial_sequence_anomalies`
5. Added CEO exception cards on the main dashboard for:
   - pending financial approvals
   - open sequence anomalies
   - today's rollback requests

## Phase 3 (Forensic-Grade: 2-4 Weeks)

### Build targets

1. Tamper-evident audit trail:
   - hash chain across financial audit events
   - periodic signed checkpoints
2. Receipt authenticity verification:
   - signed QR payload on invoice/receipt/quotation
   - verification endpoint for front-desk and auditors
3. Automated anomaly scoring:
   - unusual rollback/refund/discount rate per user
   - after-hours edit alerts
   - high-risk event notifications to CEO
4. Multi-channel reconciliation connectors:
   - mobile money settlement import
   - bank deposit matching

### Suggested backlog items

1. Add `finance_forensics` app with event hash chaining and verification jobs.
2. Add signed token utility for document QR payloads.
3. Add alert service for exception thresholds and escalation.

## Governance KPIs

1. Paid rollback attempts by role and outcome.
2. Ratio of approved vs rejected risky requests.
3. Daily reconciliation variance and unresolved exceptions.
4. Time-to-detection for high-risk events.
5. Sequence anomalies per day.
