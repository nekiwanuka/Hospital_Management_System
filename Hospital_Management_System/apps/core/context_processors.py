from django.db.utils import OperationalError, ProgrammingError

from apps.settingsapp.models import SystemSettings

_MODULE_CODES = [
    "patients",
    "visits",
    "triage",
    "consultation",
    "emergency",
    "admission",
    "laboratory",
    "radiology",
    "pharmacy",
    "inventory",
    "billing",
    "reports",
    "referrals",
]


def system_context(request):
    settings_obj = SystemSettings.objects.first()
    user_modules = {}
    can_view_revenue = False

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        # Module access map for sidebar visibility
        has_access = getattr(user, "has_module_access", None)
        for code in _MODULE_CODES:
            user_modules[code] = has_access(code) if has_access else True

        # Revenue visibility
        can_view_revenue = (
            getattr(user, "is_superuser", False)
            or getattr(user, "role", "") in ("system_admin", "director")
            or getattr(user, "can_view_revenue", False)
        )

    return {
        "system_settings": settings_obj,
        "clinic_name": settings_obj.clinic_name if settings_obj else "ClinicMS",
        "user_modules": user_modules,
        "can_view_revenue": can_view_revenue,
    }
