from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.permissions import module_permission_required, role_required
from apps.permissions.forms import UserModulePermissionForm
from apps.permissions.models import PermissionAccessRequest, UserModulePermission


@login_required
@role_required("system_admin", "director")
@module_permission_required("permissions", "view")
def index(request):
    permissions = UserModulePermission.objects.select_related(
        "user", "granted_by"
    ).order_by("module_name", "user__username")
    return render(request, "permissions/index.html", {"permissions": permissions})


def _sync_allowed_modules(user, module_name, grant=True):
    """Add or remove a module from the user's allowed_modules JSONField."""
    modules = user.allowed_modules or []
    if grant:
        if module_name not in modules:
            modules.append(module_name)
    else:
        modules = [m for m in modules if m != module_name]
    user.allowed_modules = modules
    user.save(update_fields=["allowed_modules"])


@login_required
@role_required("system_admin", "director")
@module_permission_required("permissions", "create")
def create(request):
    if request.method == "POST":
        form = UserModulePermissionForm(request.POST)
        if form.is_valid():
            permission = form.save(commit=False)
            permission.granted_by = request.user
            permission.save()
            _sync_allowed_modules(
                permission.user, permission.module_name, grant=permission.is_active
            )
            messages.success(
                request,
                f"{permission.get_module_name_display()} access granted to "
                f"{permission.user.get_full_name() or permission.user.username}.",
            )
            return redirect("permissions:index")
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
@role_required("system_admin", "director")
@module_permission_required("permissions", "update")
def update(request, pk):
    permission = get_object_or_404(UserModulePermission, pk=pk)

    if request.method == "POST":
        form = UserModulePermissionForm(request.POST, instance=permission)
        if form.is_valid():
            permission = form.save(commit=False)
            permission.granted_by = request.user
            permission.save()
            _sync_allowed_modules(
                permission.user, permission.module_name, grant=permission.is_active
            )
            messages.success(request, "Permission updated.")
            return redirect("permissions:index")
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
@role_required("system_admin", "director")
@module_permission_required("permissions", "delete")
def delete(request, pk):
    permission = get_object_or_404(UserModulePermission, pk=pk)
    if request.method == "POST":
        _sync_allowed_modules(permission.user, permission.module_name, grant=False)
        permission.delete()
        messages.success(request, "Permission removed.")
        return redirect("permissions:index")

    return render(
        request,
        "permissions/delete_confirm.html",
        {"permission": permission},
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("permissions", "update")
def toggle_permission(request, pk):
    """Suspend or reactivate a permission grant."""
    permission = get_object_or_404(UserModulePermission, pk=pk)
    if request.method != "POST":
        return redirect("permissions:index")

    if permission.is_active:
        permission.is_active = False
        permission.save(update_fields=["is_active"])
        _sync_allowed_modules(permission.user, permission.module_name, grant=False)
        messages.info(
            request,
            f"{permission.get_module_name_display()} access for "
            f"{permission.user.get_full_name() or permission.user.username} has been suspended.",
        )
    else:
        permission.is_active = True
        permission.granted_by = request.user
        permission.save(update_fields=["is_active", "granted_by", "granted_at"])
        _sync_allowed_modules(permission.user, permission.module_name, grant=True)
        messages.success(
            request,
            f"{permission.get_module_name_display()} access for "
            f"{permission.user.get_full_name() or permission.user.username} has been reactivated.",
        )
    return redirect("permissions:index")


# ---------------------------------------------------------------------------
# Permission Access Requests — any user can request, admin reviews
# ---------------------------------------------------------------------------


@login_required
def request_access(request):
    """Any authenticated user can submit an access request."""
    if request.method != "POST":
        return redirect("core:dashboard")

    module_name = (request.POST.get("module_name") or "").strip()
    reason = (request.POST.get("reason") or "").strip()

    valid_modules = {code for code, _ in UserModulePermission.MODULE_CHOICES}
    if module_name not in valid_modules:
        messages.error(request, "Invalid module selected.")
        return redirect("core:dashboard")

    # Block if user already has access to this module
    if request.user.has_module_access(module_name):
        messages.info(
            request,
            "You already have access to this module.",
        )
        return redirect("core:dashboard")

    # Prevent duplicate pending requests
    already_pending = PermissionAccessRequest.objects.filter(
        user=request.user, module_name=module_name, status="pending"
    ).exists()
    if already_pending:
        messages.info(
            request,
            "You already have a pending access request for this module.",
        )
        return redirect("core:dashboard")

    PermissionAccessRequest.objects.create(
        user=request.user,
        module_name=module_name,
        reason=reason,
    )
    messages.success(
        request,
        "Your access request has been submitted. "
        "The system administrator will review it shortly.",
    )
    return redirect("core:dashboard")


@login_required
@role_required("system_admin", "director")
def access_requests_list(request):
    """Admin/director sees all pending access requests."""
    pending = PermissionAccessRequest.objects.filter(status="pending").select_related(
        "user"
    )
    reviewed = (
        PermissionAccessRequest.objects.exclude(status="pending")
        .select_related("user", "reviewed_by")
        .order_by("-updated_at")[:50]
    )
    active_grants = (
        UserModulePermission.objects.filter(is_active=True)
        .select_related("user", "granted_by")
        .order_by("user__username", "module_name")[:50]
    )
    suspended_grants = (
        UserModulePermission.objects.filter(is_active=False)
        .select_related("user", "granted_by")
        .order_by("user__username", "module_name")[:20]
    )
    return render(
        request,
        "permissions/access_requests.html",
        {
            "pending_requests": pending,
            "reviewed_requests": reviewed,
            "active_grants": active_grants,
            "suspended_grants": suspended_grants,
        },
    )


@login_required
@role_required("system_admin", "director")
def review_access_request(request, pk):
    """Admin approves or rejects an access request."""
    access_request = get_object_or_404(PermissionAccessRequest, pk=pk, status="pending")

    if request.method == "POST":
        action = request.POST.get("action")
        reviewer_notes = (request.POST.get("reviewer_notes") or "").strip()

        if action == "approve":
            # Create or update the UserModulePermission grant
            perm, created = UserModulePermission.objects.get_or_create(
                user=access_request.user,
                module_name=access_request.module_name,
                defaults={
                    "can_view": True,
                    "can_create": True,
                    "can_update": True,
                    "is_active": True,
                    "granted_by": request.user,
                    "notes": f"Granted via access request #{access_request.pk}",
                },
            )
            if not created:
                perm.is_active = True
                perm.can_view = True
                perm.granted_by = request.user
                perm.notes = f"Re-activated via access request #{access_request.pk}"
                perm.save()

            _sync_allowed_modules(
                access_request.user, access_request.module_name, grant=True
            )

            access_request.status = "approved"
            access_request.reviewed_by = request.user
            access_request.reviewer_notes = reviewer_notes
            access_request.save()
            messages.success(
                request,
                f"Access to {access_request.get_module_name_display()} granted "
                f"for {access_request.user.username}.",
            )

        elif action == "reject":
            access_request.status = "rejected"
            access_request.reviewed_by = request.user
            access_request.reviewer_notes = reviewer_notes
            access_request.save()
            messages.info(
                request,
                f"Access request from {access_request.user.username} rejected.",
            )

        return redirect("permissions:access_requests")

    return render(
        request,
        "permissions/review_access_request.html",
        {"access_request": access_request},
    )
