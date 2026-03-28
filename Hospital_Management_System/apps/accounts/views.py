from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import UserCreateForm, UserEditForm
from .models import User
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
