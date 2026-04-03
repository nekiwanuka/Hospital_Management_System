from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def _has_explicit_module_grant(user, module_name, action="view"):
    """Return True if the user has an active UserModulePermission row
    granting the given action on the module."""
    try:
        from apps.permissions.models import UserModulePermission

        perm = UserModulePermission.objects.filter(
            user=user, module_name=module_name, is_active=True
        ).first()
        if not perm:
            return False
        action_map = {
            "view": perm.can_view,
            "create": perm.can_create,
            "update": perm.can_update,
            "soft_delete": perm.can_soft_delete,
            "hard_delete": perm.can_hard_delete,
        }
        return bool(action_map.get(action, False))
    except Exception:
        return False


def user_has_any_role(user, roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.role == "system_admin":
        return True
    return user.role in set(roles)


def role_required(*roles):
    allowed_roles = set(roles)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if user_has_any_role(request.user, allowed_roles):
                return view_func(request, *args, **kwargs)
            # Check if the next decorator granted module info; if the user
            # has an explicit module permission, let them through.
            module_name = getattr(view_func, "_module_name", None)
            action = getattr(view_func, "_module_action", "view")
            if module_name and _has_explicit_module_grant(
                request.user, module_name, action
            ):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(
                "You do not have permission to access this page. "
                "Please contact the system administrator to request access."
            )

        return _wrapped_view

    return decorator


class RoleRequiredMixin(UserPassesTestMixin):
    allowed_roles = ()

    def test_func(self):
        return user_has_any_role(self.request.user, self.allowed_roles)

    def handle_no_permission(self):
        raise PermissionDenied(
            "You do not have permission to access this page. "
            "Please contact the system administrator to request access."
        )


def branch_queryset_for_user(user, queryset):
    if not user.is_authenticated:
        return queryset.none()
    if user.is_superuser or getattr(user, "can_view_all_branches", False):
        return queryset
    if getattr(user, "branch_id", None):
        return queryset.filter(branch_id=user.branch_id)
    return queryset.none()


def get_delete_capability(user, module_name: str):
    if not user or not user.is_authenticated:
        return {"can_soft_delete": False, "can_hard_delete": False}

    if user.is_superuser or user.role == "system_admin":
        return {"can_soft_delete": True, "can_hard_delete": True}

    if user.role == "director":
        return {"can_soft_delete": True, "can_hard_delete": False}

    if not getattr(user, "can_delete_records", False):
        return {"can_soft_delete": False, "can_hard_delete": False}

    try:
        from apps.permissions.models import UserModulePermission

        permission = UserModulePermission.objects.filter(
            user=user, module_name=module_name
        ).first()
    except Exception:
        permission = None

    if not permission:
        return {"can_soft_delete": False, "can_hard_delete": False}

    return {
        "can_soft_delete": permission.can_soft_delete,
        "can_hard_delete": permission.can_hard_delete,
    }


def has_module_action_permission(user, module_name: str, action: str) -> bool:
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.role == "system_admin":
        return True

    # Check module-level access
    if hasattr(user, "has_module_access") and not user.has_module_access(module_name):
        return False

    if action in {"soft_delete", "hard_delete"}:
        capability = get_delete_capability(user, module_name)
        return (
            capability["can_soft_delete"]
            if action == "soft_delete"
            else capability["can_hard_delete"]
        )

    # Check for explicit per-user module permission overrides
    try:
        from apps.permissions.models import UserModulePermission

        permission = UserModulePermission.objects.filter(
            user=user,
            module_name=module_name,
            is_active=True,
        ).first()
    except Exception:
        permission = None

    # If an explicit permission row exists, it takes authority
    if permission:
        action_map = {
            "view": permission.can_view,
            "create": permission.can_create,
            "update": permission.can_update,
            "soft_delete": permission.can_soft_delete,
            "hard_delete": permission.can_hard_delete,
        }
        return bool(action_map.get(action, False))

    # No explicit override — users with role-based module access can
    # view, create, and update by default.
    if action in {"view", "create", "update"}:
        return True

    return False


def module_permission_required(module_name: str, action: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if has_module_action_permission(request.user, module_name, action):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied(
                "You do not have permission to access this page. "
                "Please contact the system administrator to request access."
            )

        # Tag the wrapper so that role_required (outer decorator) can read
        # the module name and fall back to explicit permission grants.
        _wrapped_view._module_name = module_name
        _wrapped_view._module_action = action
        return _wrapped_view

    return decorator
