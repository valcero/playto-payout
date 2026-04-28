import uuid

from django.db import models, transaction
from django.db.models import Sum, Q
from django.utils import timezone


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
        balance always derived from ledger entries at the DB level.
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
        available_balance = credits - debits - held_balance #net balance

        #all in paise
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


class IdempotencyKey(models.Model):
    """
    Stores the idempotency key and its cached response.
    Created with response_body=None when a request starts processing.
    Filled in when the request completes. This lets us detect in-flight duplicates.
    """
    key = models.UUIDField()
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="idempotency_keys"
    )
    response_status = models.IntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["merchant", "key"],
                name="unique_idempotency_key_per_merchant",
            ),
        ]

    def is_expired(self):
        return self.created_at < timezone.now() - timezone.timedelta(hours=24)

    def is_complete(self):
        return self.response_status is not None

    def __str__(self):
        return f"IdempotencyKey {self.key} [{self.merchant.name}]"


class Payout(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Every legal transition. If a (from, to) pair isn't here, it's illegal.
    # processing → pending exists solely for retry — the retry worker resets
    # timed-out payouts so they get re-picked. Terminal states (completed, failed)
    # have no entry: they allow nothing.
    VALID_TRANSITIONS = {
        Status.PENDING: {Status.PROCESSING},
        Status.PROCESSING: {Status.COMPLETED, Status.FAILED, Status.PENDING},
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(
        Merchant, on_delete=models.CASCADE, related_name="payouts"
    )
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="payouts"
    )
    amount_paise = models.BigIntegerField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["merchant", "status"]),
            models.Index(fields=["status", "last_attempt_at"]),
        ]

    def __str__(self):
        return f"Payout {self.id} — {self.amount_paise}p [{self.status}]"

    def transition_to(self, new_status):
        
        #Enforce state machine.
        #This is the ONLY way status should ever change.
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {self.status} → {new_status}. "
                f"Allowed from {self.status}: {allowed or 'none (terminal state)'}"
            )
        self.status = new_status
        self.updated_at = timezone.now()

    @transaction.atomic
    def mark_processing(self):
        #Worker picks up this payout. Increment attempt counter
        self.transition_to(self.Status.PROCESSING)
        self.attempts += 1
        self.last_attempt_at = timezone.now()
        self.save(update_fields=["status", "attempts", "last_attempt_at", "updated_at"])

    @transaction.atomic
    def mark_completed(self):
        """
        Bank confirmed settlement. Release the hold and create a debit.
        Both ledger entries + status change happen in one transaction —
        if any part fails, nothing commits.
        """
        self.transition_to(self.Status.COMPLETED)
        self.save(update_fields=["status", "updated_at"])

        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.RELEASE,
            amount_paise=self.amount_paise,
            description=f"Payout {self.id} settled",
            reference_id=self.id,
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount_paise=self.amount_paise,
            description=f"Payout {self.id} settled",
            reference_id=self.id,
        )

    @transaction.atomic
    def mark_failed(self):
        """
        Bank rejected or max retries hit. Release held funds back to merchant.
        if the release entry fails to write, status stays processing.
        """
        self.transition_to(self.Status.FAILED)
        self.save(update_fields=["status", "updated_at"])

        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type=LedgerEntry.EntryType.RELEASE,
            amount_paise=self.amount_paise,
            description=f"Payout {self.id} failed — funds returned",
            reference_id=self.id,
        )
