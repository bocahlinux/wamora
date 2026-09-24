import logging

from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    """Consistent JSON error envelope for every DRF view (docs/07-API-CONTRACT.md
    API principle: "consistent errors"). Never echoes raw exception text back
    to the client — internal details (e.g. DB connection errors) are logged
    server-side only, per the log-redaction / no-secret-leakage requirement
    in docs/06-SECURITY.md.
    """
    request = context.get('request')
    request_id = getattr(request, 'request_id', None)

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.exception('Unhandled exception in API view', exc_info=exc)
        return Response(
            {
                'error': {
                    'code': 'internal_error',
                    'message': 'Internal server error',
                    'request_id': request_id,
                }
            },
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    message = detail.get('detail') if isinstance(detail, dict) else detail
    response.data = {
        'error': {
            'code': getattr(exc, 'default_code', exc.__class__.__name__.lower()),
            'message': message,
            'request_id': request_id,
        }
    }
    return response
