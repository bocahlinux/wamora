import logging

from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.webhooks.authentication import WEBHOOK_SIGNATURE_HEADER, verify_waha_webhook_signature
from apps.webhooks.parsing import EnvelopeValidationError, parse_envelope
from apps.webhooks.services import ingest_webhook

logger = logging.getLogger(__name__)


class WahaWebhookView(APIView):
    """Receives WAHA webhook deliveries.

    WAHA is a machine caller, authenticated by a shared-secret HMAC
    signature (see authentication.py) rather than Django/DRF user auth —
    hence empty authentication_classes/permission_classes and a manual
    signature check here. Uses DRF's request.data/JSONParser and the
    project-wide EXCEPTION_HANDLER (apps.core.exceptions.api_exception_handler)
    so malformed JSON and unhandled errors get the same request-ID/error-
    envelope treatment as every other endpoint (docs/07-API-CONTRACT.md).
    """

    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser]

    def post(self, request, *args, **kwargs):
        request_id = getattr(request, 'request_id', None)

        signature = request.META.get(WEBHOOK_SIGNATURE_HEADER)
        if not verify_waha_webhook_signature(request.body, signature):
            logger.warning('Rejected webhook request: invalid or missing signature')
            return Response(
                {
                    'error': {
                        'code': 'unauthorized',
                        'message': 'Invalid webhook signature',
                        'request_id': request_id,
                    }
                },
                status=401,
            )

        # Malformed JSON raises DRF's ParseError here, handled by the
        # project's shared EXCEPTION_HANDLER -> consistent 400 envelope.
        data = request.data

        try:
            envelope = parse_envelope(data)
        except EnvelopeValidationError as exc:
            return Response(
                {'error': {'code': 'invalid_envelope', 'message': str(exc), 'request_id': request_id}},
                status=400,
            )

        webhook_event = ingest_webhook(envelope)

        return Response(
            {
                'status': 'ok',
                'webhook_event_id': webhook_event.pk,
                'processing_status': webhook_event.status,
            }
        )
