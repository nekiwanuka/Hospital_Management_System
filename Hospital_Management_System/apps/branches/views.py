from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import module_permission_required, role_required
from apps.branches.forms import BranchForm
from apps.branches.models import Branch


@login_required
@module_permission_required("branches", "view")
def index(request):
    if request.user.can_view_all_branches:
        queryset = Branch.objects.order_by("branch_name")
    else:
        queryset = Branch.objects.filter(id=request.user.branch_id)

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(branch_name__icontains=query)
            | Q(location__icontains=query)
            | Q(contact_number__icontains=query)
        )

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "branches/index.html",
        {
            "branches": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("branches", "create")
def create_branch(request):
    if request.method == "POST":
        form = BranchForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settingsapp:index")
    else:
        form = BranchForm()
    return render(
        request,
        "branches/form.html",
        {"form": form, "page_title": "Create Branch", "submit_label": "Create Branch"},
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("branches", "update")
def edit_branch(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == "POST":
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            return redirect("settingsapp:index")
    else:
        form = BranchForm(instance=branch)
    return render(
        request,
        "branches/form.html",
        {
            "form": form,
            "page_title": f"Edit Branch — {branch.branch_name}",
            "submit_label": "Save Changes",
        },
    )
