import hashlib
import hmac

from django.conf import settings

WEBHOOK_SIGNATURE_HEADER = 'HTTP_X_WEBHOOK_HMAC'


def verify_waha_webhook_signature(raw_body: bytes, signature_header) -> bool:
    """Verifies a WAHA webhook delivery's HMAC-SHA512 signature.

    UNVERIFIED ASSUMPTION (see docs/generated/PHASE-3-WEBHOOK-INGESTION.md,
    "Known limitations"): this matches WAHA's own publicly documented
    webhook HMAC feature (`X-Webhook-Hmac` header, HMAC-SHA512 of the raw
    request body, secret configured on the WAHA session's webhook config)
    — it has NOT been confirmed against this project's actual deployed WAHA
    instance, since no live access was available while this was written.
    Confirm the WAHA-side webhook configuration matches before relying on
    this in production.

    Fails closed: an unconfigured secret, or a missing/invalid signature,
    is always rejected — never treated as "no auth required".
    """
    secret = settings.WAHA_WEBHOOK_HMAC_SECRET
    if not secret or not signature_header:
        return False
    expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip().lower())
