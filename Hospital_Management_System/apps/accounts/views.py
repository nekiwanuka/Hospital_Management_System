from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    UserCreateForm,
    UserEditForm,
    OpenShiftForm,
    CloseShiftForm,
    AssignSecretCodeForm,
)
from .models import User, Shift, ShiftSecretCode
from apps.core.permissions import module_permission_required, role_required


class ClinicLoginView(LoginView):
    template_name = "accounts/login.html"


class ClinicLogoutView(LogoutView):
    next_page = "accounts:login"


@login_required
@role_required("system_admin", "director")
@module_permission_required("accounts", "view")
def users_index(request):
    queryset = User.objects.select_related("branch").order_by("username")

    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )

    role = request.GET.get("role", "").strip()
    if role:
        queryset = queryset.filter(role=role)

    paginator = Paginator(queryset, 15)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/index.html",
        {
            "users": page_obj.object_list,
            "page_obj": page_obj,
            "query": query,
            "role_filter": role,
            "role_choices": User.ROLE_CHOICES if hasattr(User, "ROLE_CHOICES") else [],
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("accounts", "create")
def create_user(request):
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("settingsapp:index")
    else:
        form = UserCreateForm()

    return render(
        request,
        "accounts/form.html",
        {
            "form": form,
            "page_title": "Create User",
            "submit_label": "Create User",
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("accounts", "update")
def edit_user(request, pk):
    user_obj = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UserEditForm(request.POST, instance=user_obj)
        if form.is_valid():
            form.save()
            return redirect("settingsapp:index")
    else:
        form = UserEditForm(instance=user_obj)

    return render(
        request,
        "accounts/form.html",
        {
            "form": form,
            "page_title": f"Edit User — {user_obj.username}",
            "submit_label": "Save Changes",
        },
    )


@login_required
@role_required("system_admin", "director")
@module_permission_required("accounts", "update")
@require_POST
def toggle_user_status(request, pk):
    user_obj = get_object_or_404(User, pk=pk)
    if user_obj == request.user:
        messages.error(request, "You cannot suspend your own account.")
    else:
        user_obj.is_active = not user_obj.is_active
        User.objects.filter(pk=pk).update(is_active=user_obj.is_active)
        action = "activated" if user_obj.is_active else "suspended"
        messages.success(request, f"User {user_obj.username} has been {action}.")
    return redirect("settingsapp:index")


# ── Shift Management ────────────────────────────────────────────────


@login_required
def open_shift(request):
    """Open a new shift — user enters name, title and secret code."""
    # Already have an open shift?
    existing = Shift.objects.filter(user=request.user, status="open").first()
    if existing:
        messages.info(request, "You already have an open shift.")
        return redirect("core:dashboard")

    if request.method == "POST":
        form = OpenShiftForm(request.POST, user=request.user)
        if form.is_valid():
            Shift.objects.create(
                user=request.user,
                branch=request.user.branch,
                status="open",
                notes=f"Opened by {form.cleaned_data['full_name']} ({form.cleaned_data['title']})",
            )
            messages.success(request, "Shift opened successfully. You may now proceed.")
            return redirect("core:dashboard")
    else:
        form = OpenShiftForm(
            user=request.user,
            initial={
                "full_name": request.user.get_full_name(),
                "title": request.user.get_role_display(),
            },
        )

    return render(request, "accounts/open_shift.html", {"form": form})


@login_required
def close_shift(request):
    """Close the currently open shift."""
    shift = Shift.objects.filter(user=request.user, status="open").first()
    if not shift:
        messages.warning(request, "No open shift to close.")
        return redirect("core:dashboard")

    if request.method == "POST":
        form = CloseShiftForm(request.POST)
        if form.is_valid():
            shift.closed_at = timezone.now()
            shift.status = "closed"
            if form.cleaned_data["notes"]:
                shift.notes += f"\n--- Handover ---\n{form.cleaned_data['notes']}"
            shift.save(update_fields=["closed_at", "status", "notes"])
            messages.success(request, "Shift closed. Thank you for your service today.")
            return redirect("accounts:login")
    else:
        form = CloseShiftForm()

    return render(request, "accounts/close_shift.html", {"form": form, "shift": shift})


@login_required
def shift_history(request):
    """View shift history for the current user (admin sees all)."""
    if request.user.role in ("system_admin", "director") or request.user.is_superuser:
        shifts = Shift.objects.select_related("user", "branch").all()
    else:
        shifts = Shift.objects.filter(user=request.user).select_related("branch")

    user_filter = request.GET.get("user", "").strip()
    if user_filter:
        shifts = shifts.filter(
            Q(user__username__icontains=user_filter)
            | Q(user__first_name__icontains=user_filter)
            | Q(user__last_name__icontains=user_filter)
        )

    paginator = Paginator(shifts, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "accounts/shift_history.html",
        {
            "shifts": page_obj.object_list,
            "page_obj": page_obj,
            "user_filter": user_filter,
            "is_admin": request.user.role in ("system_admin", "director")
            or request.user.is_superuser,
        },
    )


# ── Secret Code Management (Admin only) ─────────────────────────────


@login_required
@role_required("system_admin", "director")
def manage_secret_codes(request):
    """View all secret codes and assign/regenerate."""
    codes = ShiftSecretCode.objects.select_related("user").order_by("user__username")

    if request.method == "POST":
        form = AssignSecretCodeForm(request.POST)
        if form.is_valid():
            target_user = form.cleaned_data["user"]
            new_code = ShiftSecretCode.generate_code()
            obj, created = ShiftSecretCode.objects.update_or_create(
                user=target_user,
                defaults={"code": new_code},
            )
            action = "assigned" if created else "regenerated"
            messages.success(
                request,
                f"Secret code {action} for {target_user.get_full_name() or target_user.username}: {new_code}",
            )
            return redirect("accounts:manage_secret_codes")
    else:
        form = AssignSecretCodeForm()

    return render(
        request,
        "accounts/manage_secret_codes.html",
        {
            "codes": codes,
            "form": form,
        },
    )
