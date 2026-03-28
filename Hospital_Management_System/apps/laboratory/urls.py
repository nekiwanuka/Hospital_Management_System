from django.urls import path

from apps.laboratory import views

app_name = "laboratory"

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "medical-store-request/",
        views.request_medical_store_stock,
        name="request_medical_store_stock",
    ),
    path("results/feed/", views.result_feed_queue, name="result_feed_queue"),
    path("<int:pk>/", views.detail, name="detail"),
    path(
        "<int:pk>/consumables/",
        views.record_consumables,
        name="record_consumables",
    ),
    path(
        "<int:pk>/consumables/correct/",
        views.correct_consumables,
        name="correct_consumables",
    ),
    path("<int:pk>/print/", views.print_result, name="print_result"),
    path("<int:pk>/results/", views.update_result, name="update_result"),
    path(
        "<int:pk>/download-pdf/", views.download_result_pdf, name="download_result_pdf"
    ),
]
