import uuid

from django.db import models
from django.db.models import Sum, Q


class Merchant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def get_balance(self):
        """
        Balance is NEVER stored — always derived from ledger entries at the DB level.
        Returns dict with available_balance, held_balance, and total_credits/debits.
        All values in paise.
        """
        agg = self.ledger_entries.aggregate(
            total_credits=Sum(
                "amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.CREDIT)
            ),
            total_debits=Sum(
                "amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.DEBIT)
            ),
            total_holds=Sum(
                "amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.HOLD)
            ),
            total_releases=Sum(
                "amount_paise", filter=Q(entry_type=LedgerEntry.EntryType.RELEASE)
            ),
        )
        credits = agg["total_credits"] or 0
        debits = agg["total_debits"] or 0
        holds = agg["total_holds"] or 0
        releases = agg["total_releases"] or 0

        held_balance = holds - releases
        available_balance = credits - debits - held_balance

        return {
            "available_balance_paise": available_balance,
            "held_balance_paise": held_balance,
            "total_credits_paise": credits,
            "total_debits_paise": debits,
        }


class BankAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="bank_accounts"
    )
    account_number = models.CharField(max_length=20)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.account_holder_name} - {self.account_number[-4:]}"


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CREDIT = "credit", "Credit"
        DEBIT = "debit", "Debit"
        HOLD = "hold", "Hold"
        RELEASE = "release", "Release"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="ledger_entries"
    )
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    amount_paise = models.BigIntegerField()
    description = models.CharField(max_length=255, blank=True, default="")
    reference_id = models.UUIDField(
        null=True, blank=True, db_index=True,
        help_text="Links to the payout or transaction that created this entry",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "entry_type"]),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount_paise}p - {self.merchant.name}"

    def save(self, *args, **kwargs):
        if self.amount_paise <= 0:
            raise ValueError("Ledger entry amount must be positive")
        super().save(*args, **kwargs)
