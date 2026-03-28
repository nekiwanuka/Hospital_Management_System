from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.core.permissions import module_permission_required
from apps.branches.models import Branch


@login_required
@module_permission_required("branches", "view")
def index(request):
    if request.user.can_view_all_branches:
        queryset = Branch.objects.order_by("branch_name")
    else:
        queryset = Branch.objects.filter(id=request.user.branch_id)
    paginator = Paginator(queryset, 5)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "branches/index.html",
        {"branches": page_obj.object_list, "page_obj": page_obj},
    )
