from django.utils import timezone

from apps.visits.models import VisitQueueEvent


def transition_visit(visit, new_status, moved_by, notes=""):
    old_status = visit.status
    if old_status == new_status:
        return visit

    visit.status = new_status
    if new_status == "completed" and visit.check_out_time is None:
        visit.check_out_time = timezone.now()
        visit.save(update_fields=["status", "check_out_time", "updated_at"])
    else:
        visit.save(update_fields=["status", "updated_at"])

    VisitQueueEvent.objects.create(
        visit=visit,
        branch=visit.branch,
        from_status=old_status,
        to_status=new_status,
        moved_by=moved_by,
        notes=notes,
    )
    return visit
