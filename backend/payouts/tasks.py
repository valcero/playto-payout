import logging
import random
import time
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Payout

logger = logging.getLogger(__name__)

BANK_SETTLE_DELAY = (1, 3)
STUCK_THRESHOLD_SECONDS = 30
MAX_ATTEMPTS = 3


def _simulate_bank_response():
    """
    Simulates a bank API call.
    Returns: "success" (70%), "failure" (20%), "timeout" (10%)
    """
    time.sleep(random.uniform(*BANK_SETTLE_DELAY))
    roll = random.random()
    if roll < 0.70:
        return "success"
    elif roll < 0.90:
        return "failure"
    return "timeout"


@shared_task(bind=True)
def process_payout(self, payout_id):
    """
    Picks up a pending payout, locks it, transitions to processing,
    and calls the bank. Uses select_for_update so two workers
    can't grab the same row.
    """
    try:
        with transaction.atomic():
            payout = (
                Payout.objects
                .select_for_update(skip_locked=True)
                .get(id=payout_id, status=Payout.Status.PENDING)
            )
            payout.mark_processing()
    except Payout.DoesNotExist:
        logger.info("Payout %s already picked up or doesn't exist", payout_id)
        return

    _settle_with_bank(payout)


def _settle_with_bank(payout):
    """Calls the bank and handles the three outcomes."""
    logger.info("Processing payout %s (attempt %d/%d)", payout.id, payout.attempts, MAX_ATTEMPTS)

    result = _simulate_bank_response()

    if result == "success":
        payout.mark_completed()
        logger.info("Payout %s completed", payout.id)
    elif result == "failure":
        payout.mark_failed()
        logger.info("Payout %s failed — funds returned", payout.id)
    else:
        logger.warning("Payout %s timed out on attempt %d — left in processing", payout.id, payout.attempts)


@shared_task
def process_pending_payouts():
    """
    Periodic task: finds all pending payouts and dispatches
    each one to its own process_payout task.
    One task per payout keeps failures isolated.
    """
    pending_ids = list(
        Payout.objects
        .filter(status=Payout.Status.PENDING)
        .values_list("id", flat=True)
    )

    if not pending_ids:
        return "No pending payouts"

    for payout_id in pending_ids:
        process_payout.delay(str(payout_id))

    return f"Dispatched {len(pending_ids)} payouts"


@shared_task
def retry_stuck_payouts():
    """
    Periodic task: finds payouts stuck in 'processing' beyond the threshold.

    For each stuck payout:
    - If attempts < MAX_ATTEMPTS: reset to pending so process_pending_payouts
      picks it up again. The backoff is enforced by the threshold check —
      attempt N must wait N * STUCK_THRESHOLD_SECONDS before being retried.
    - If attempts >= MAX_ATTEMPTS: move to failed and return funds.
    """
    stuck = list(
        Payout.objects
        .filter(status=Payout.Status.PROCESSING)
        .select_related("merchant")
    )

    if not stuck:
        return "No stuck payouts"

    retried = 0
    failed = 0

    for payout in stuck:
        # Exponential backoff: attempt 1 waits 30s, attempt 2 waits 60s, attempt 3 waits 90s
        backoff_seconds = STUCK_THRESHOLD_SECONDS * payout.attempts
        cutoff = timezone.now() - timedelta(seconds=backoff_seconds)

        if payout.last_attempt_at and payout.last_attempt_at > cutoff:
            continue

        with transaction.atomic():
            payout = (
                Payout.objects
                .select_for_update()
                .get(id=payout.id)
            )
            if payout.status != Payout.Status.PROCESSING:
                continue

            if payout.attempts >= MAX_ATTEMPTS:
                payout.mark_failed()
                logger.info(
                    "Payout %s exhausted %d attempts — failed, funds returned",
                    payout.id, MAX_ATTEMPTS,
                )
                failed += 1
            else:
                payout.transition_to(Payout.Status.PENDING)
                payout.save(update_fields=["status", "updated_at"])
                logger.info(
                    "Payout %s reset to pending for retry (attempt %d/%d)",
                    payout.id, payout.attempts, MAX_ATTEMPTS,
                )
                retried += 1

    return f"Retried {retried}, failed {failed}"
