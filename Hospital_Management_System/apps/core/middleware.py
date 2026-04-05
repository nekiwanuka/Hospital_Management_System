import json

from apps.settingsapp.models import SystemSettings


class BranchContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.branch = None
        if hasattr(request, "user") and request.user.is_authenticated:
            # Directors / system admins may temporarily view another branch
            switched_id = request.session.get("switched_branch_id")
            if switched_id and getattr(request.user, "can_view_all_branches", False):
                from apps.branches.models import Branch

                request.branch = (
                    Branch.objects.filter(pk=switched_id, status="active").first()
                    or request.user.branch
                )
            else:
                request.branch = request.user.branch
        response = self.get_response(request)
        return response


class ShiftRequiredMiddleware:
    """
    After login, redirect to the 'open shift' page if the user
    does not have an active shift. Exempt paths: login, logout,
    static/media, admin, shift open itself, and setup.
    """

    EXEMPT_PREFIXES = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/shift/open/",
        "/static/",
        "/media/",
        "/admin/",
        "/setup/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    EXEMPT_ROLES = ("system_admin", "director")

    def __call__(self, request):
        if (
            hasattr(request, "user")
            and request.user.is_authenticated
            and not request.path.startswith(self.EXEMPT_PREFIXES)
            and not request.user.is_superuser
            and getattr(request.user, "role", None) not in self.EXEMPT_ROLES
        ):
            from apps.accounts.models import Shift

            has_open_shift = Shift.objects.filter(
                user=request.user, status="open"
            ).exists()
            if not has_open_shift:
                from django.shortcuts import redirect

                return redirect("accounts:open_shift")

        return self.get_response(request)


class SetupRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setup_paths = ("/setup/", "/admin/", "/static/", "/media/")
        if not request.path.startswith(setup_paths):
            if not SystemSettings.objects.filter(is_initialized=True).exists():
                from django.shortcuts import redirect

                return redirect("core:setup")
        return self.get_response(request)


class AuditLogMiddleware:
    WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
    EXCLUDED_PREFIXES = ("/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            not hasattr(request, "user")
            or not request.user.is_authenticated
            or request.method not in self.WRITE_METHODS
            or request.path.startswith(self.EXCLUDED_PREFIXES)
        ):
            return response

        from apps.core.models import AuditLog

        object_type = request.path.strip("/").split("/")[0] or "core"
        details = {
            "path": request.path,
            "method": request.method,
            "status_code": response.status_code,
        }

        try:
            AuditLog.objects.create(
                user=request.user,
                branch=getattr(request, "branch", None),
                action=request.method,
                object_type=object_type,
                details=json.dumps(details),
                ip_address=self._get_client_ip(request),
            )
        except Exception:
            # Do not block requests if audit persistence fails.
            pass

        return response

    def _get_client_ip(self, request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
