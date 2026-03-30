from django.urls import path

from apps.reports import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("profit/", views.profit_report, name="profit"),
    path(
        "profit/laboratory/",
        views.laboratory_profitability_report,
        name="laboratory_profitability",
    ),
    path(
        "profit/radiology/",
        views.radiology_profitability_report,
        name="radiology_profitability",
    ),
    path(
        "profit/pharmacy/",
        views.pharmacy_profitability_report,
        name="pharmacy_profitability",
    ),
    path("export/", views.export_report, name="export"),
]
