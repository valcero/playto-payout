import logging
import random
import time

from celery import shared_task
from django.db import transaction

from .models import Payout

logger = logging.getLogger(__name__)

BANK_SETTLE_DELAY = (1, 3)


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
    Uses select_for_update on the payout row so two workers
    can't process the same payout concurrently.
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

    logger.info("Processing payout %s (attempt %d)", payout_id, payout.attempts)

    result = _simulate_bank_response()

    if result == "success":
        payout.mark_completed()
        logger.info("Payout %s completed", payout_id)
    elif result == "failure":
        payout.mark_failed()
        logger.info("Payout %s failed — funds returned", payout_id)
    else:
        # Timeout 
        logger.warning("Payout %s timed out — left in processing", payout_id)


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
