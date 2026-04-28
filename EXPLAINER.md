# EXPLAINER

## 1. The Ledger

**Balance calculation query** (from `payouts/models.py`, `Merchant.get_balance`):

```python
agg = self.ledger_entries.aggregate(
    total_credits=Sum("amount_paise", filter=Q(entry_type="credit")),
    total_debits=Sum("amount_paise", filter=Q(entry_type="debit")),
    total_holds=Sum("amount_paise", filter=Q(entry_type="hold")),
    total_releases=Sum("amount_paise", filter=Q(entry_type="release")),
)
credits = agg["total_credits"] or 0
debits = agg["total_debits"] or 0
holds = agg["total_holds"] or 0
releases = agg["total_releases"] or 0

held_balance = holds - releases
available_balance = credits - debits - held_balance
```

**Why this model?**

There is no `balance` column anywhere. Balance is always computed by summing ledger entries in a single database query. This means the invariant "sum of credits minus debits equals displayed balance" is true by construction — it's impossible for it to drift.

I use four entry types instead of two. `credit` and `debit` track money in and out. `hold` and `release` track money that's promised but not yet moved. When a payout is requested, I create a `hold`. When it completes, I create a `release` + `debit`. When it fails, I just `release`. This gives the dashboard two numbers: available balance (what you can withdraw) and held balance (what's in flight).

All amounts are `BigIntegerField` in paise. No floats, no decimals. Integer arithmetic has no rounding errors.

---

## 2. The Lock

**The exact code** (from `payouts/views.py`, `PayoutCreateView.post`):

```python
with transaction.atomic():
    # This line is the lock
    Merchant.objects.select_for_update().get(id=merchant_id)

    balance = merchant.get_balance()
    available = balance["available_balance_paise"]

    if amount > available:
        return Response({"error": "Insufficient balance"}, status=422)

    payout = Payout.objects.create(...)
    LedgerEntry.objects.create(entry_type="hold", amount_paise=amount, ...)
```

**What database primitive it relies on:**

`select_for_update()` translates to `SELECT ... FOR UPDATE` in PostgreSQL. This acquires a row-level exclusive lock on the merchant row. Any other transaction that tries to `SELECT FOR UPDATE` on the same row will block until the first transaction commits or rolls back.

This matters because the balance check and the hold creation must happen atomically. Without the lock, two threads could both read "balance = 10000", both decide "6000 < 10000, proceed", and both create holds — overdrawing the account. With the lock, the second thread waits until the first commits its hold, then reads the updated balance (now 4000), and correctly rejects the second 6000 request.

This is a database-level lock, not a Python-level lock. It works across Gunicorn workers, across machines, across anything that talks to the same Postgres instance.

---

## 3. The Idempotency

**How the system knows it has seen a key before:**

There's an `IdempotencyKey` model with a `UNIQUE` constraint on `(merchant_id, key)`. When a request arrives:

1. Try `INSERT` into the idempotency table
2. If INSERT succeeds → new request, proceed normally
3. If INSERT fails with `IntegrityError` → key already exists

The database's unique constraint is the source of truth, not a SELECT check. Two threads racing to claim the same key will have exactly one INSERT succeed and one fail — there's no window for a race condition.

**What happens if the first request is still in flight:**

When the first request starts, it creates an `IdempotencyKey` row with `response_body=NULL`. When it finishes, it fills in the response. If a second request arrives while the first is still processing, it finds the row with `response_body=NULL` and returns `409 Conflict`. This tells the client "your request is being processed, don't retry yet."

The code (from `payouts/idempotency.py`):

```python
try:
    with transaction.atomic():
        return IdempotencyKey.objects.create(key=key_uuid, merchant_id=merchant_id)
except IntegrityError:
    pass

existing = IdempotencyKey.objects.get(key=key_uuid, merchant_id=merchant_id)

if not existing.is_complete():      # response_body is still NULL
    return Response({"error": "Already being processed"}, status=409)

return Response(existing.response_body, status=existing.response_status)  # replay
```

---

## 4. The State Machine

**Where `failed → completed` is blocked** (from `payouts/models.py`, `Payout.transition_to`):

```python
VALID_TRANSITIONS = {
    Status.PENDING: {Status.PROCESSING},
    Status.PROCESSING: {Status.COMPLETED, Status.FAILED, Status.PENDING},
    # completed and failed have NO entry — they are terminal states
}

def transition_to(self, new_status):
    allowed = self.VALID_TRANSITIONS.get(self.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Illegal transition: {self.status} → {new_status}. "
            f"Allowed from {self.status}: {allowed or 'none (terminal state)'}"
        )
    self.status = new_status
```

`completed` and `failed` are not keys in `VALID_TRANSITIONS`. So `self.VALID_TRANSITIONS.get("completed")` returns `None`, which becomes an empty `set()`. Any transition from `completed` (including `completed → pending`) fails the `if new_status not in allowed` check and raises `ValueError`.

Every status change in the codebase goes through `transition_to()` — there's no direct `payout.status = "completed"` anywhere. `mark_processing()`, `mark_completed()`, and `mark_failed()` all call `transition_to()` first.

---

## 5. The AI Audit

**The bug: balance check outside the lock**

AI initially generated the payout view with the balance check *before* the `select_for_update()` call:

```python
# WRONG — what AI gave me
balance = merchant.get_balance()  # reads balance here
available = balance["available_balance_paise"]

with transaction.atomic():
    Merchant.objects.select_for_update().get(id=merchant_id)
    # balance was already read OUTSIDE the lock!
    if amount > available:
        return Response({"error": "Insufficient balance"}, status=422)
    LedgerEntry.objects.create(entry_type="hold", ...)
```

**Why it's wrong:** The balance is computed before the lock is acquired. Between the read and the lock, another thread could commit a hold, changing the balance. Thread 1 reads "10000", Thread 2 reads "10000", both acquire the lock sequentially, both think they have 10000 available, both create 6000 holds — overdraft.

**What I replaced it with:**

```python
# CORRECT — balance computed inside the lock
with transaction.atomic():
    Merchant.objects.select_for_update().get(id=merchant_id)
    balance = merchant.get_balance()  # now inside the lock
    available = balance["available_balance_paise"]
    if amount > available:
        return Response({"error": "Insufficient balance"}, status=422)
    LedgerEntry.objects.create(entry_type="hold", ...)
```

Moving `get_balance()` inside the `transaction.atomic()` block, after `select_for_update()`, means the balance read happens while holding the exclusive lock. No other transaction can modify the merchant's ledger entries between the read and the write.
