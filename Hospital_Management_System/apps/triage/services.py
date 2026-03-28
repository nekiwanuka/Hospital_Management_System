from apps.billing.models import Invoice
from apps.consultation.models import Consultation
from apps.core.permissions import branch_queryset_for_user
from apps.visits.models import Visit


def get_triage_eligible_visits(user):
    visits = list(
        branch_queryset_for_user(
            user,
            Visit.objects.select_related("patient")
            .filter(status="waiting_triage", check_out_time__isnull=True)
            .order_by("-check_in_time"),
        )
    )

    eligible_visits = []
    for visit in visits:
        payment_cleared = branch_queryset_for_user(
            user,
            Invoice.objects.filter(visit=visit, payment_status="paid"),
        ).exists()

        review_privilege = None
        if not payment_cleared:
            review_privilege = branch_queryset_for_user(
                user,
                Consultation.objects.filter(
                    patient=visit.patient,
                    follow_up_date__isnull=False,
                    follow_up_date__gte=visit.check_in_time.date(),
                    created_at__lte=visit.check_in_time,
                ).order_by("-follow_up_date", "-created_at"),
            ).first()

        if payment_cleared or review_privilege:
            visit.triage_clearance_type = (
                "paid" if payment_cleared else "post_payment_privilege"
            )
            visit.triage_clearance_label = (
                "Paid"
                if payment_cleared
                else f"Post-payment privilege until {review_privilege.follow_up_date}"
            )
            eligible_visits.append(visit)

    return eligible_visits


def get_triage_eligible_visit_ids(user):
    return [visit.pk for visit in get_triage_eligible_visits(user)]


def visit_has_triage_clearance(user, visit):
    if not visit:
        return False
    return visit.pk in set(get_triage_eligible_visit_ids(user))
