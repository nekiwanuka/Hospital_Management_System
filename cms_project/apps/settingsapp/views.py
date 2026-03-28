from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.branches.models import Branch
from apps.core.permissions import module_permission_required, role_required
from apps.permissions.models import UserModulePermission
from apps.settingsapp.forms import InstallationWizardForm, SystemSettingsForm
from apps.settingsapp.models import SystemSettings


@require_http_methods(["GET", "POST"])
def install_wizard(request):
    if SystemSettings.objects.filter(is_initialized=True).exists():
        return redirect("accounts:login")

    if request.method == "POST":
        form = InstallationWizardForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    settings_obj = form.save(commit=False)
                    settings_obj.is_initialized = True
                    settings_obj.save()

                    branch = Branch.objects.create(
                        branch_name=form.cleaned_data["branch_name"],
                        branch_code=form.cleaned_data["branch_code"],
                        address=form.cleaned_data["branch_address"],
                        city=form.cleaned_data["branch_city"],
                        country=form.cleaned_data["branch_country"],
                        phone=form.cleaned_data["branch_phone"],
                        email=form.cleaned_data["branch_email"],
                        status="active",
                    )

                    User = get_user_model()
                    user = User.objects.create_user(
                        username=form.cleaned_data["admin_username"],
                        email=form.cleaned_data["admin_email"],
                        password=form.cleaned_data["admin_password"],
                        first_name=form.cleaned_data.get("admin_first_name", ""),
                        last_name=form.cleaned_data.get("admin_last_name", ""),
                        phone=form.cleaned_data.get("admin_phone", ""),
                        role="system_admin",
                        branch=branch,
                        is_staff=True,
                        is_superuser=True,
                    )
                    user.save()
            except IntegrityError:
                form.add_error(
                    "admin_username", "A user with that username already exists."
                )
            else:
                messages.success(request, "Setup complete. Please sign in.")
                return redirect("accounts:login")
    else:
        form = InstallationWizardForm()

    return render(request, "settingsapp/install_wizard.html", {"form": form})


@login_required
@role_required("system_admin", "director")
@module_permission_required("settingsapp", "update")
def edit_settings(request):
    """Edit system settings (system_admin only)."""
    settings_obj = SystemSettings.objects.first()
    if not settings_obj:
        messages.warning(request, "Run the setup wizard first.")
        return redirect("settingsapp:install")

    if request.method == "POST":
        form = SystemSettingsForm(request.POST, request.FILES, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "System settings updated.")
            return redirect("settingsapp:index")
    else:
        form = SystemSettingsForm(instance=settings_obj)

    return render(
        request,
        "settingsapp/edit_settings.html",
        {"form": form, "settings_obj": settings_obj},
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("settingsapp", "view")
def index(request):
    """Unified administration hub — settings, branches, users, permissions."""
    User = get_user_model()
    tab = request.GET.get("tab", "general")

    settings_obj = SystemSettings.objects.first()

    if request.user.can_view_all_branches:
        branches = Branch.objects.order_by("branch_name")
    else:
        branches = Branch.objects.filter(id=request.user.branch_id)

    users = User.objects.select_related("branch").order_by("username")

    is_sys_admin = request.user.is_superuser or request.user.role == "system_admin"
    can_manage_settings = is_sys_admin or request.user.role == "director"
    permissions = (
        UserModulePermission.objects.select_related("user", "granted_by").order_by(
            "module_name", "user__username"
        )
        if is_sys_admin
        else UserModulePermission.objects.none()
    )

    # Build role-defaults matrix for template
    module_choices = User.MODULE_ACCESS_CHOICES
    role_defaults = []
    for role_code, role_label in User.ROLE_CHOICES:
        defaults = User.ROLE_DEFAULT_MODULES.get(
            role_code, [c for c, _ in module_choices]
        )
        role_defaults.append((role_code, role_label, defaults))

    return render(
        request,
        "settingsapp/index.html",
        {
            "settings_obj": settings_obj,
            "branches": branches,
            "users": users,
            "permissions": permissions,
            "active_tab": tab,
            "is_sys_admin": is_sys_admin,
            "can_manage_settings": can_manage_settings,
            "role_defaults": role_defaults,
            "module_choices": module_choices,
        },
    )
