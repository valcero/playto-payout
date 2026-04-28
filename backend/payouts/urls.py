from django.urls import path

from . import views

urlpatterns = [
    path(
        "merchants/<uuid:merchant_id>/payouts/",
        views.PayoutCreateView.as_view(),
        name="payout-create",
    ),
]
