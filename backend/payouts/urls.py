from django.urls import path

from . import views

urlpatterns = [
    path(
        "merchants/",
        views.MerchantListView.as_view(),
        name="merchant-list",
    ),
    path(
        "merchants/<uuid:merchant_id>/",
        views.MerchantDetailView.as_view(),
        name="merchant-detail",
    ),
    path(
        "merchants/<uuid:merchant_id>/ledger/",
        views.MerchantLedgerView.as_view(),
        name="merchant-ledger",
    ),
    path(
        "merchants/<uuid:merchant_id>/bank-accounts/",
        views.MerchantBankAccountsView.as_view(),
        name="merchant-bank-accounts",
    ),
    path(
        "merchants/<uuid:merchant_id>/payouts/",
        views.PayoutCreateView.as_view(),
        name="payout-create",
    ),
    path(
        "merchants/<uuid:merchant_id>/payouts/history/",
        views.MerchantPayoutsView.as_view(),
        name="payout-history",
    ),
]
