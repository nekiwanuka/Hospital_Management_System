from django.urls import path

from apps.consultation import views

app_name = "consultation"

urlpatterns = [
    path("", views.index, name="index"),
    path("start-next/", views.start_next, name="start_next"),
    path("review/<int:visit_id>/", views.nurse_review, name="nurse_review"),
    path("start/<int:visit_id>/", views.start, name="start"),
    path(
        "start/<int:visit_id>/discharge/",
        views.discharge_patient,
        name="discharge_patient",
    ),
    path(
        "start/<int:visit_id>/complete/",
        views.complete_visit,
        name="complete_visit",
    ),
    path(
        "start/<int:visit_id>/transfer/",
        views.transfer_patient,
        name="transfer_patient",
    ),
    path(
        "start/<int:visit_id>/request-lab/",
        views.request_lab_test,
        name="request_lab_test",
    ),
    path(
        "start/<int:visit_id>/labs/<int:lab_request_id>/review/",
        views.review_lab_result,
        name="review_lab_result",
    ),
    path(
        "start/<int:visit_id>/request-radiology/",
        views.request_radiology,
        name="request_radiology",
    ),
    path(
        "start/<int:visit_id>/request-referral/",
        views.request_referral,
        name="request_referral",
    ),
    path(
        "start/<int:visit_id>/request-pharmacy/",
        views.request_pharmacy,
        name="request_pharmacy",
    ),
    path(
        "start/<int:visit_id>/send-to-cashier/",
        views.send_to_cashier,
        name="send_to_cashier",
    ),
    path(
        "api/medicine-search/",
        views.medicine_search_api,
        name="medicine_search_api",
    ),
]
