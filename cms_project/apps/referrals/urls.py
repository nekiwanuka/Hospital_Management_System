from django.urls import path

from apps.referrals import views

app_name = "referrals"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create, name="create"),
]
