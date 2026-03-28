from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.core.permissions import (
    branch_queryset_for_user,
    module_permission_required,
    role_required,
)
from apps.emergency.forms import EmergencyCaseForm
from apps.emergency.models import EmergencyCase
from apps.visits.services import transition_visit


@login_required
@role_required(
    "receptionist", "triage_officer", "doctor", "nurse", "system_admin", "director"
)
@module_permission_required("emergency", "view")
def index(request):
    queryset = branch_queryset_for_user(
        request.user,
        EmergencyCase.objects.select_related("patient", "doctor").order_by("-date"),
    )
    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "emergency/index.html",
        {"cases": page_obj.object_list, "page_obj": page_obj},
    )


@login_required
@role_required(
    "receptionist", "triage_officer", "doctor", "nurse", "system_admin", "director"
)
@module_permission_required("emergency", "create")
def create(request):
    if request.method == "POST":
        form = EmergencyCaseForm(request.POST, user=request.user)
        if form.is_valid():
            if not request.user.branch_id:
                form.add_error(None, "Your user account has no branch assigned.")
            else:
                emergency_case = form.save(commit=False)
                emergency_case.branch = request.user.branch
                emergency_case.save()
                if emergency_case.visit:
                    emergency_case.visit.visit_type = "emergency"
                    emergency_case.visit.save(
                        update_fields=["visit_type", "updated_at"]
                    )
                    transition_visit(emergency_case.visit, "in_triage", request.user)
                return redirect("emergency:index")
    else:
        form = EmergencyCaseForm(user=request.user)

    return render(
        request,
        "emergency/form.html",
        {
            "form": form,
            "page_title": "New Emergency Case",
            "submit_label": "Save Emergency Case",
        },
    )
