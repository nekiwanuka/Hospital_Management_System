from django.urls import path

from apps.billing import views

app_name = "billing"

urlpatterns = [
    path("", views.index, name="index"),
    path("shifts/open/", views.open_shift, name="open_shift"),
    path("shifts/<int:shift_id>/close/", views.close_shift, name="close_shift"),
    path("shifts/report/", views.shift_sessions_report, name="shift_sessions_report"),
    path("payments/", views.payments_register, name="payments_register"),
    path("approvals/", views.approval_requests, name="approval_requests"),
    path(
        "approvals/<int:request_id>/review/",
        views.review_approval_request,
        name="review_approval_request",
    ),
    path("sequence-anomalies/", views.sequence_anomalies, name="sequence_anomalies"),
    path("create/", views.create, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/invoice/", views.invoice_document, name="invoice_document"),
    path("<int:pk>/quotation/", views.quotation_document, name="quotation_document"),
    path("<int:pk>/payment/", views.update_payment_status, name="update_payment"),
    path("<int:pk>/line/<int:line_id>/pay/", views.pay_line_item, name="pay_line_item"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("receipt/<int:receipt_pk>/", views.receipt_detail, name="receipt_detail"),
]
