from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.core.views import permission_denied_view

handler403 = permission_denied_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.inventory.api_urls")),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("branches/", include("apps.branches.urls")),
    path("patients/", include("apps.patients.urls")),
    path("triage/", include("apps.triage.urls")),
    path("consultation/", include("apps.consultation.urls")),
    path("laboratory/", include("apps.laboratory.urls")),
    path("radiology/", include("apps.radiology.urls")),
    path("pharmacy/", include("apps.pharmacy.urls")),
    path("billing/", include("apps.billing.urls")),
    path("admission/", include("apps.admission.urls")),
    path("delivery/", include("apps.delivery.urls")),
    path("referrals/", include("apps.referrals.urls")),
    path("emergency/", include("apps.emergency.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("visits/", include("apps.visits.urls")),
    path("permissions/", include("apps.permissions.urls")),
    path("reports/", include("apps.reports.urls")),
    path("system/", include("apps.settingsapp.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
