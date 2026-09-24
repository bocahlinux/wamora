import uuid


class RequestIDMiddleware:
    """Assigns a request ID to every request/response (docs/07-API-CONTRACT.md
    API principle: "request IDs"). Reuses an incoming X-Request-ID header
    when present so upstream (BFF) IDs propagate end to end."""

    HEADER_NAME = 'X-Request-ID'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.META.get('HTTP_X_REQUEST_ID') or str(uuid.uuid4())
        response = self.get_response(request)
        response[self.HEADER_NAME] = request.request_id
        return response
