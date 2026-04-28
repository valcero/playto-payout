import uuid
from concurrent.futures import ThreadPoolExecutor

from django.db import connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from payouts.models import BankAccount, LedgerEntry, Merchant, Payout


class ConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name="Test Merchant")
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number="1234567890",
            ifsc_code="HDFC0001234",
            account_holder_name="Test Account",
        )
        # Give the merchant ₹100
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=10000,
            description="Initial deposit",
        )

    def _make_payout_request(self, amount_paise):
        #sends a payout request with a unique idempotency key
        try:
            client = APIClient()
            return client.post(
                "/api/v1/payouts/",
                data={
                    "amount_paise": amount_paise,
                    "bank_account_id": str(self.bank_account.id),
                },
                format="json",
                HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
            )
        finally:
            connections.close_all()

    def test_two_concurrent_payouts_only_one_succeeds(self):
        # Use a thread pool to send both requests at the same time
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_1 = pool.submit(self._make_payout_request, 6000)
            future_2 = pool.submit(self._make_payout_request, 6000)
            response_1 = future_1.result()
            response_2 = future_2.result()

        statuses = sorted([response_1.status_code, response_2.status_code])

        self.assertEqual(statuses, [201, 422])

        self.assertEqual(Payout.objects.count(), 1)

        balance = self.merchant.get_balance()
        self.assertEqual(balance["available_balance_paise"], 4000)
        self.assertEqual(balance["held_balance_paise"], 6000)


class IdempotencyTest(TransactionTestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(name="Idempotency Merchant")
        self.bank_account = BankAccount.objects.create(
            merchant=self.merchant,
            account_number="9876543210",
            ifsc_code="ICIC0005678",
            account_holder_name="Idempotency Account",
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.CREDIT,
            amount_paise=50000,
            description="Initial deposit",
        )

    def test_same_key_returns_same_response_no_duplicate(self):
        client = APIClient()
        idempotency_key = str(uuid.uuid4())

        payload = {
            "amount_paise": 5000,
            "bank_account_id": str(self.bank_account.id),
        }

        #creates the payout
        response_1 = client.post(
            "/api/v1/payouts/",
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        self.assertEqual(response_1.status_code, 201)

        response_2 = client.post(
            "/api/v1/payouts/",
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        self.assertEqual(response_2.status_code, 201)
        self.assertEqual(response_1.data["id"], response_2.data["id"])

        self.assertEqual(Payout.objects.count(), 1)

    def test_different_keys_create_separate_payouts(self):
        client = APIClient()

        payload = {
            "amount_paise": 5000,
            "bank_account_id": str(self.bank_account.id),
        }

        response_1 = client.post(
            "/api/v1/payouts/",
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        response_2 = client.post(
            "/api/v1/payouts/",
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )

        self.assertEqual(response_1.status_code, 201)
        self.assertEqual(response_2.status_code, 201)
        self.assertNotEqual(response_1.data["id"], response_2.data["id"])
        self.assertEqual(Payout.objects.count(), 2)
