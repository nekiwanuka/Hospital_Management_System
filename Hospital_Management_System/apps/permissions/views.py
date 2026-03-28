from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import module_permission_required, role_required
from apps.permissions.forms import UserModulePermissionForm
from apps.permissions.models import UserModulePermission


@login_required
@role_required("system_admin")
@module_permission_required("permissions", "view")
def index(request):
    permissions = UserModulePermission.objects.select_related(
        "user", "granted_by"
    ).order_by("module_name", "user__username")
    return render(request, "permissions/index.html", {"permissions": permissions})


@login_required
@role_required("system_admin")
@module_permission_required("permissions", "create")
def create(request):
    if request.method == "POST":
        form = UserModulePermissionForm(request.POST)
        if form.is_valid():
            permission = form.save(commit=False)
            permission.granted_by = request.user
            permission.save()
            return redirect("settingsapp:index")
    else:
        form = UserModulePermissionForm()

    return render(
        request,
        "permissions/form.html",
        {
            "form": form,
            "page_title": "Grant Module Permission",
            "submit_label": "Save Permission",
        },
    )


@login_required
@role_required("system_admin")
@module_permission_required("permissions", "update")
def update(request, pk):
    permission = get_object_or_404(UserModulePermission, pk=pk)

    if request.method == "POST":
        form = UserModulePermissionForm(request.POST, instance=permission)
        if form.is_valid():
            permission = form.save(commit=False)
            permission.granted_by = request.user
            permission.save()
            return redirect("settingsapp:index")
    else:
        form = UserModulePermissionForm(instance=permission)

    return render(
        request,
        "permissions/form.html",
        {
            "form": form,
            "page_title": "Update Module Permission",
            "submit_label": "Update Permission",
        },
    )


@login_required
@role_required("system_admin")
@module_permission_required("permissions", "delete")
def delete(request, pk):
    permission = get_object_or_404(UserModulePermission, pk=pk)
    if request.method == "POST":
        permission.delete()
        return redirect("settingsapp:index")

    return render(
        request,
        "permissions/delete_confirm.html",
        {"permission": permission},
    )
