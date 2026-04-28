from django.db import transaction
from django.db.models import Sum, Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .idempotency import idempotent
from .models import BankAccount, LedgerEntry, Merchant, Payout
from .serializers import (
    BankAccountSerializer,
    LedgerEntrySerializer,
    MerchantListSerializer,
    MerchantSerializer,
    PayoutRequestSerializer,
    PayoutResponseSerializer,
)


def _merchant_id_from_request(request, **kwargs):
    bank_account_id = request.data.get("bank_account_id")
    if not bank_account_id:
        return None

    try:
        return BankAccount.objects.only("merchant_id").get(id=bank_account_id).merchant_id
    except (BankAccount.DoesNotExist, ValueError, TypeError):
        return None


class MerchantListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.all()
        return Response(MerchantListSerializer(merchants, many=True).data)


class MerchantDetailView(APIView):
    def get(self, request, merchant_id):
        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response({"error": "Merchant not found"}, status=404)
        return Response(MerchantSerializer(merchant).data)


class MerchantLedgerView(APIView):
    def get(self, request, merchant_id):
        entries = LedgerEntry.objects.filter(merchant_id=merchant_id)
        return Response(LedgerEntrySerializer(entries, many=True).data)


class MerchantBankAccountsView(APIView):
    def get(self, request, merchant_id):
        accounts = BankAccount.objects.filter(merchant_id=merchant_id)
        return Response(BankAccountSerializer(accounts, many=True).data)


class MerchantPayoutsView(APIView):
    def get(self, request, merchant_id):
        payouts = Payout.objects.filter(merchant_id=merchant_id)
        return Response(PayoutResponseSerializer(payouts, many=True).data)


class PayoutCreateView(APIView):
    """
    Uses SELECT FOR UPDATE on the merchant row to serialize
    concurrent payout requests — only one can check-and-deduct at a time.
    """

    @idempotent(_merchant_id_from_request)
    def post(self, request):
        merchant_id = _merchant_id_from_request(request)
        if not merchant_id:
            return Response(
                {"error": "Bank account not found or does not belong to a merchant"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            merchant = Merchant.objects.get(id=merchant_id)
        except Merchant.DoesNotExist:
            return Response(
                {"error": "Merchant not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = PayoutRequestSerializer(
            data=request.data,
            context={"merchant": merchant},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        amount = serializer.validated_data["amount_paise"]
        bank_account_id = serializer.validated_data["bank_account_id"]

        #from here to the end of the `with` block is serialized
        with transaction.atomic():
            # SELECT ... FOR UPDATE acquires an exclusive row lock on this merchant. A second concurrent request for the same merchant
            # will block here until this transaction commits.
            # this is a db lock,it works across processes, across machines
            Merchant.objects.select_for_update().get(id=merchant_id)

            # Compute balance INSIDE the lock. If we computed it before
            # locking, another transaction could commit a hold between
            # our read and our write — classic check-then-act race.
            balance = merchant.get_balance()
            available = balance["available_balance_paise"]

            if amount > available:
                return Response(
                    {
                        "error": "Insufficient balance",
                        "available_balance_paise": available,
                        "requested_paise": amount,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )

            bank_account = BankAccount.objects.get(id=bank_account_id)
            payout = Payout.objects.create(
                merchant=merchant,
                bank_account=bank_account,
                amount_paise=amount,
            )

            LedgerEntry.objects.create(
                merchant=merchant,
                entry_type=LedgerEntry.EntryType.HOLD,
                amount_paise=amount,
                description=f"Payout {payout.id} hold",
                reference_id=payout.id,
            )

        response_data = PayoutResponseSerializer(payout).data
        return Response(response_data, status=status.HTTP_201_CREATED)
