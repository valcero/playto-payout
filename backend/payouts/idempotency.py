import uuid
from datetime import timedelta
from functools import wraps

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from .models import IdempotencyKey


def idempotent(get_merchant_id):
    """
    Decorator for DRF view methods that enforces idempotency.

    get_merchant_id: callable(request, **kwargs) -> UUID
        Extracts the merchant ID from the incoming request.

    Flow:
    1. Parse Idempotency-Key header (required, must be valid UUID)
    2. Try INSERT into idempotency_keys — DB unique constraint is the lock
    3. If INSERT succeeds: this is a new request, proceed normally
    4. If INSERT fails (IntegrityError): key exists, three sub-cases:
       a. Key expired (>24h old) — delete and retry as new
       b. Key still processing (response_body is None) — return 409
       c. Key completed — return the cached response
    5. After view executes, store response in the key row
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(view_instance, request, *args, **kwargs):
            raw_key = request.META.get("HTTP_IDEMPOTENCY_KEY")
            if not raw_key:
                return Response(
                    {"error": "Idempotency-Key header is required"},
                    status=400,
                )

            try:
                key_uuid = uuid.UUID(raw_key)
            except ValueError:
                return Response(
                    {"error": "Idempotency-Key must be a valid UUID"},
                    status=400,
                )

            merchant_id = get_merchant_id(request, **kwargs)

            idem_key = _claim_or_retrieve(key_uuid, merchant_id)
            if isinstance(idem_key, Response):
                return idem_key

            response = view_func(view_instance, request, *args, **kwargs)

            idem_key.response_status = response.status_code
            idem_key.response_body = response.data
            idem_key.save(update_fields=["response_status", "response_body"])

            return response

        return wrapper

    return decorator


def _claim_or_retrieve(key_uuid, merchant_id):
    """
    Try to claim an idempotency key. Returns the IdempotencyKey object
    if this is a new request, or a Response if it's a duplicate.

    Uses INSERT with a unique constraint as the concurrency primitive —
    two threads racing to claim the same key will have exactly one win
    and one hit IntegrityError. No SELECT-then-INSERT race.
    """
    try:
        with transaction.atomic():
            return IdempotencyKey.objects.create(
                key=key_uuid,
                merchant_id=merchant_id,
            )
    except IntegrityError:
        pass

    existing = IdempotencyKey.objects.get(key=key_uuid, merchant_id=merchant_id)

    if existing.created_at < timezone.now() - timedelta(hours=24):
        existing.delete()
        return IdempotencyKey.objects.create(
            key=key_uuid,
            merchant_id=merchant_id,
        )

    if not existing.is_complete():
        return Response(
            {"error": "A request with this idempotency key is already being processed"},
            status=409,
        )

    return Response(existing.response_body, status=existing.response_status)
