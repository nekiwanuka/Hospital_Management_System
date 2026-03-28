import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-secret-key")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.core",
    "apps.accounts",
    "apps.branches",
    "apps.patients",
    "apps.triage",
    "apps.consultation",
    "apps.laboratory",
    "apps.radiology",
    "apps.pharmacy",
    "apps.billing",
    "apps.admission",
    "apps.referrals",
    "apps.emergency",
    "apps.inventory",
    "apps.visits",
    "apps.permissions",
    "apps.reports",
    "apps.settingsapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AuditLogMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.BranchContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.system_context",
            ],
            "libraries": {
                "currency": "apps.core.templatetags.currency",
            },
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def _sqlite_db(path: str):
    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / path)}


def _postgres_db(parsed):
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/") or "clinicms",
        "USER": parsed.username or "postgres",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "127.0.0.1",
        "PORT": str(parsed.port or 5432),
    }


def _mysql_db(parsed):
    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": parsed.path.lstrip("/") or "clinicms",
        "USER": parsed.username or "root",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "127.0.0.1",
        "PORT": str(parsed.port or 3306),
        "OPTIONS": {"charset": "utf8mb4"},
    }


database_url = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
parsed = urlparse(database_url)
if parsed.scheme.startswith("postgres"):
    DATABASES = {"default": _postgres_db(parsed)}
elif parsed.scheme.startswith("mysql"):
    DATABASES = {"default": _mysql_db(parsed)}
else:
    rel = parsed.path.lstrip("/") if parsed.path else "db.sqlite3"
    DATABASES = {"default": _sqlite_db(rel or "db.sqlite3")}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_BROWSER_XSS_FILTER = True

if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

# ---------------------------------------------------------------------------
# Jazzmin admin theme
# ---------------------------------------------------------------------------
JAZZMIN_SETTINGS = {
    "site_title": "HMS Admin",
    "site_header": "Hospital Management System",
    "site_brand": "HMS",
    "site_logo": None,
    "login_logo": None,
    "welcome_sign": "Welcome to HMS Administration",
    "copyright": "Hospital Management System",
    "search_model": ["accounts.User", "patients.Patient"],
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"name": "Back to HMS", "url": "/", "new_window": False},
    ],
    "show_sidebar": True,
    "navigation_expanded": False,
    "icons": {
        "auth": "fas fa-users-cog",
        "accounts": "fas fa-users",
        "accounts.User": "fas fa-user-md",
        "branches.Branch": "fas fa-hospital",
        "patients.Patient": "fas fa-procedures",
        "visits.Visit": "fas fa-walking",
        "visits.VisitQueueEvent": "fas fa-exchange-alt",
        "consultation.Consultation": "fas fa-stethoscope",
        "triage.TriageRecord": "fas fa-heartbeat",
        "laboratory.LabRequest": "fas fa-flask",
        "radiology.ImagingRequest": "fas fa-x-ray",
        "radiology.ImagingResult": "fas fa-file-medical-alt",
        "radiology.RadiologyType": "fas fa-list-alt",
        "radiology.RadiologyQueue": "fas fa-clipboard-list",
        "radiology.RadiologyImage": "fas fa-images",
        "pharmacy.Medicine": "fas fa-pills",
        "pharmacy.DispenseRecord": "fas fa-prescription-bottle-alt",
        "pharmacy.DispenseBatchAllocation": "fas fa-layer-group",
        "pharmacy.MedicalStoreRequest": "fas fa-truck",
        "pharmacy.PharmacyRequest": "fas fa-file-prescription",
        "billing.Invoice": "fas fa-file-invoice-dollar",
        "billing.InvoiceLineItem": "fas fa-receipt",
        "billing.Receipt": "fas fa-money-check-alt",
        "admission.Admission": "fas fa-bed",
        "emergency.EmergencyCase": "fas fa-ambulance",
        "referrals.Referral": "fas fa-share",
        "inventory.Item": "fas fa-boxes",
        "inventory.Batch": "fas fa-cubes",
        "inventory.Category": "fas fa-tags",
        "inventory.Brand": "fas fa-copyright",
        "inventory.Supplier": "fas fa-truck-loading",
        "inventory.StockMovement": "fas fa-exchange-alt",
        "inventory.Dispense": "fas fa-hand-holding-medical",
        "inventory.DispenseItem": "fas fa-capsules",
        "inventory.StockItem": "fas fa-warehouse",
        "inventory.StockIssue": "fas fa-exclamation-triangle",
        "inventory.InventoryStoreProfile": "fas fa-store",
        "reports.GeneratedReport": "fas fa-chart-bar",
        "permissions.UserModulePermission": "fas fa-user-shield",
        "core.AuditLog": "fas fa-clipboard-list",
        "core.DeleteRequest": "fas fa-trash-alt",
    },
    "default_icon_parents": "fas fa-folder",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": True,
    "use_google_fonts_cdn": True,
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        "accounts.User": "collapsible",
    },
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-primary",
    "navbar": "navbar-dark",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": True,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme": "cosmo",
    "dark_mode_theme": "darkly",
    "button_classes": {
        "primary": "btn-primary",
        "secondary": "btn-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}
