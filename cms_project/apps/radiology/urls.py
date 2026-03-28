from django.urls import path

from apps.radiology import views

app_name = "radiology"

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "medical-store-request/",
        views.request_medical_store_stock,
        name="request_medical_store_stock",
    ),
    path(
        "medical-store-request/xray/",
        views.request_xray_stock,
        name="request_xray_stock",
    ),
    path(
        "medical-store-request/ultrasound/",
        views.request_ultrasound_stock,
        name="request_ultrasound_stock",
    ),
    path("feed-results/", views.result_feed_queue, name="result_feed_queue"),
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
    path("<int:pk>/result/", views.upload_result, name="upload_result"),
    path("<int:pk>/images/upload/", views.upload_images, name="upload_images"),
    path(
        "<int:pk>/workflow/<str:action>/",
        views.update_workflow,
        name="update_workflow",
    ),
    path("<int:pk>/viewer/", views.viewer, name="viewer"),
    path(
        "<int:pk>/compare/",
        views.compare_with_previous,
        name="compare_with_previous",
    ),
    path(
        "<int:pk>/notify/",
        views.notify_requesting_doctor,
        name="notify_requesting_doctor",
    ),
    path("ultrasound/", views.ultrasound, name="ultrasound"),
    path("xray/", views.xray, name="xray"),
]
