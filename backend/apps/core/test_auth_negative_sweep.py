"""Phase 13 (Failure/security testing) Track A, scope item 1 — a
systematic auth-negative sweep across every Django endpoint in this
project.

`docs/generated/PHASE-13-FAILURE-SECURITY-TESTING-SCOPING-AUDIT-REPORT.md`
scope item 1 asks for something the many existing *per-view* auth tests
(`apps.dashboard.tests.test_views`, `apps.chats.test_views`,
`apps.sync.tests.test_views`, `apps.blast.tests.test_views`, ...) do not
provide: a single, systematic sweep that (a) will not silently miss a
newly added endpoint, and (b) directly reproduces the shape of Phase 12
finding #1 (`MessagesStatsView`/`ActivityFeedView`/`SyncStatusView`
shipped with only `IsAuthenticated`, no `HasReadingScope` — any
authenticated user, scoped or not, could read them).

Two complementary, permanent regression guards:

1. `EndpointRegistryExhaustivenessTests.test_every_apps_view_is_registered`
   walks the REAL URL configuration (`django.urls.get_resolver()` — the
   same resolver Django itself dispatches against, not a hand-maintained
   copy of `urls.py`) and asserts every class-based view under `apps.*`
   has been explicitly classified in `ENDPOINT_REGISTRY` below (as
   `public`, `internal_key`, `authenticated_only`, or `scoped`). A brand
   new view that forgets `permission_classes` cannot silently ship
   unnoticed: this test fails on the very next `manage.py test` run until
   someone consciously adds it to the registry.

2. `AuthNegativeSweepTests` then walks `ENDPOINT_REGISTRY` and, for every
   `scoped`/`authenticated_only` entry, fires a real HTTP request with NO
   Authorization header through Django's APITestCase client and asserts
   401; for every `scoped` entry it additionally fires a request with a
   validly-signed JWT belonging to a user with NO scope Groups at all and
   asserts 403. This is a BEHAVIORAL check, not a config-introspection
   check — it exercises the exact code path a real client would hit.
   Reasoned through concretely against Phase 12 finding #1 (not
   re-enacted against real application code, per this task's scope
   boundary — reasoning only): before that fix, `MessagesStatsView`'s
   `permission_classes` was `[IsAuthenticated]` only. A no-scope-Groups
   but authenticated user satisfies `IsAuthenticated` (it's a real,
   logged-in user — it simply has no scope Groups), so the view would
   have returned 200, not 403. This test's
   `self.assertEqual(response.status_code, 403, ...)` for that exact
   request shape would have failed loudly (`200 != 403`) had it existed
   at the time — i.e. this is a genuine, not hypothetical, regression
   catch for that finding's exact shape.
   `internal_key` entries get the equivalent check against
   `apps.core.internal_auth.HasInternalServiceKey` (missing header -> 403,
   matching that permission's own documented fail-closed behavior and
   `apps.core.test_internal_auth.py`'s existing unit coverage of the
   permission class itself).

`public` entries (health checks, login, the WAHA webhook endpoint — which
uses its own HMAC signature scheme, not JWT/DRF permissions at all) are
listed only so the exhaustiveness check above can account for every view;
their own already-adequate negative coverage lives in
`apps.webhooks.tests.test_views.WebhookSecurityTests` and
`apps.authn.tests.test_views`, not duplicated here.
"""

from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import get_resolver
from rest_framework.test import APITestCase

from apps.audit.views import AuditEventCreateView
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.authn.views import LoginView, MeView
from apps.blast.views import (
    BlastCampaignApproveView,
    BlastCampaignDetailView,
    BlastCampaignListCreateView,
    BlastCampaignRejectView,
    BlastCampaignSubmitView,
    BlastRecipientResolveView,
)
from apps.chats.views import ChatListView, ChatMarkReadView, ChatMessagesView
from apps.core.views import DatabaseHealthView, LivenessView, RedisHealthView
from apps.dashboard.views import ActivityFeedView, MessagesStatsView
from apps.operations.views import OutboundOperationRegisterView, OutboundOperationResolveView
from apps.sync.internal_views import ReconciliationTriggerView
from apps.sync.views import SyncCheckpointRecoveryView, SyncCheckpointTaskStateView, SyncStatusView
from apps.webhooks.views import WahaWebhookView

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
TEST_INTERNAL_SERVICE_KEY = 'sweep-test-internal-service-key'

# Non-existent-but-well-formed path parameters. Every permission check in
# this project's views runs in DRF's `initial()`, before the view's own
# `get()`/`post()` body or any `get_object_or_404()` call — so a
# nonexistent pk/session_name is deliberately used throughout: if a
# regression ever made permission checks run AFTER object lookup instead,
# these would start returning 404 instead of 401/403 and this sweep would
# catch that too.
NONEXISTENT_PK = 999999
NONEXISTENT_SESSION = 'nonexistent-session'

# kind values:
#   'public'            — no Django/DRF auth at all, by design (health
#                          checks, login, the WAHA-webhook HMAC endpoint).
#                          Listed only for the exhaustiveness check.
#   'internal_key'       — apps.core.internal_auth.HasInternalServiceKey,
#                          BFF/Celery-only, no JWT.
#   'authenticated_only' — plain IsAuthenticated, no scope requirement.
#   'scoped'             — IsAuthenticated + at least one scope-checking
#                          permission (HasReadingScope, HasBlastScope,
#                          HasSystemAdministrationScope, or an OR of them).
ENDPOINT_REGISTRY = [
    # --- public -------------------------------------------------------
    {'view': LivenessView, 'method': 'get', 'url': '/api/health/', 'kind': 'public'},
    {'view': DatabaseHealthView, 'method': 'get', 'url': '/api/health/database/', 'kind': 'public'},
    {'view': RedisHealthView, 'method': 'get', 'url': '/api/health/redis/', 'kind': 'public'},
    {'view': LoginView, 'method': 'post', 'url': '/api/auth/login/', 'kind': 'public'},
    {'view': WahaWebhookView, 'method': 'post', 'url': '/api/webhooks/waha/', 'kind': 'public'},
    # --- authenticated-only (no scope requirement) --------------------
    {'view': MeView, 'method': 'get', 'url': '/api/auth/me/', 'kind': 'authenticated_only'},
    # --- scoped (JWT + a specific scope permission) --------------------
    {'view': MessagesStatsView, 'method': 'get', 'url': '/api/dashboard/messages/', 'kind': 'scoped'},
    {'view': ActivityFeedView, 'method': 'get', 'url': '/api/dashboard/activity/', 'kind': 'scoped'},
    {'view': ChatListView, 'method': 'get', 'url': '/api/chats/', 'kind': 'scoped'},
    {
        'view': ChatMessagesView,
        'method': 'get',
        'url': f'/api/chats/{NONEXISTENT_PK}/messages/',
        'kind': 'scoped',
    },
    {
        'view': ChatMarkReadView,
        'method': 'post',
        'url': f'/api/chats/{NONEXISTENT_PK}/read/',
        'kind': 'scoped',
    },
    {
        'view': SyncStatusView,
        'method': 'get',
        'url': f'/api/sync/status/{NONEXISTENT_SESSION}/',
        'kind': 'scoped',
    },
    {
        'view': SyncCheckpointRecoveryView,
        'method': 'post',
        'url': f'/api/sync/recover/{NONEXISTENT_SESSION}/',
        'kind': 'scoped',
    },
    {
        'view': SyncCheckpointTaskStateView,
        'method': 'get',
        'url': f'/api/sync/task-state/{NONEXISTENT_SESSION}/',
        'kind': 'scoped',
    },
    {'view': BlastCampaignListCreateView, 'method': 'get', 'url': '/api/blast/campaigns/', 'kind': 'scoped'},
    {'view': BlastCampaignListCreateView, 'method': 'post', 'url': '/api/blast/campaigns/', 'kind': 'scoped'},
    {
        'view': BlastCampaignDetailView,
        'method': 'get',
        'url': f'/api/blast/campaigns/{NONEXISTENT_PK}/',
        'kind': 'scoped',
    },
    {
        'view': BlastCampaignSubmitView,
        'method': 'post',
        'url': f'/api/blast/campaigns/{NONEXISTENT_PK}/submit/',
        'kind': 'scoped',
    },
    {
        'view': BlastCampaignApproveView,
        'method': 'post',
        'url': f'/api/blast/campaigns/{NONEXISTENT_PK}/approve/',
        'kind': 'scoped',
    },
    {
        'view': BlastCampaignRejectView,
        'method': 'post',
        'url': f'/api/blast/campaigns/{NONEXISTENT_PK}/reject/',
        'kind': 'scoped',
    },
    {
        'view': BlastRecipientResolveView,
        'method': 'post',
        'url': f'/api/blast/campaigns/{NONEXISTENT_PK}/recipients/{NONEXISTENT_PK}/resolve/',
        'kind': 'scoped',
    },
    # --- internal-service-key (BFF/Celery, no JWT) ----------------------
    {
        'view': OutboundOperationRegisterView,
        'method': 'post',
        'url': '/internal/outbound-operations/',
        'kind': 'internal_key',
    },
    {
        'view': OutboundOperationResolveView,
        'method': 'patch',
        'url': f'/internal/outbound-operations/{NONEXISTENT_PK}/',
        'kind': 'internal_key',
    },
    {'view': AuditEventCreateView, 'method': 'post', 'url': '/internal/audit-events/', 'kind': 'internal_key'},
    {
        'view': ReconciliationTriggerView,
        'method': 'post',
        'url': '/internal/reconciliation/trigger/',
        'kind': 'internal_key',
    },
]

REGISTERED_VIEW_CLASSES = {entry['view'] for entry in ENDPOINT_REGISTRY}


def _walk_url_patterns(patterns, prefix=''):
    """Recursively yields every leaf URLPattern's resolved view class
    (or None for function-based/admin views), mirroring exactly what
    django.urls.get_resolver() would dispatch to at runtime."""
    for entry in patterns:
        if hasattr(entry, 'url_patterns'):  # URLResolver (an include())
            yield from _walk_url_patterns(entry.url_patterns, prefix + str(entry.pattern))
        else:  # URLPattern (a leaf)
            cls = getattr(entry.callback, 'cls', None)
            yield prefix + str(entry.pattern), cls


class EndpointRegistryExhaustivenessTests(APITestCase):
    """Guards against a brand new endpoint shipping without ever being
    classified as public/internal/scoped — the structural precondition
    for Phase 12 finding #1 happening again, on a *new* view this time."""

    def test_every_apps_view_is_registered(self):
        unregistered = []
        for path, cls in _walk_url_patterns(get_resolver().url_patterns):
            if cls is None:
                continue  # admin.site.urls and friends — not this project's own code
            if not cls.__module__.startswith('apps.'):
                continue
            if cls not in REGISTERED_VIEW_CLASSES:
                unregistered.append((path, cls))

        self.assertEqual(
            unregistered,
            [],
            'Endpoint(s) added to urls.py without being classified in '
            'ENDPOINT_REGISTRY (backend/apps/core/test_auth_negative_sweep.py) — '
            'add an entry (public/internal_key/authenticated_only/scoped) '
            'before shipping a new view: ' + repr(unregistered),
        )

    def test_registry_itself_only_references_real_apps_views(self):
        """The inverse check: catches a registry entry that has gone
        stale (view renamed/removed from urls.py) rather than silently
        testing nothing."""
        live_classes = {
            cls for _, cls in _walk_url_patterns(get_resolver().url_patterns) if cls is not None
        }
        stale = REGISTERED_VIEW_CLASSES - live_classes
        self.assertEqual(stale, set(), f'ENDPOINT_REGISTRY references view(s) no longer mounted: {stale}')


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
    INTERNAL_SERVICE_KEY=TEST_INTERNAL_SERVICE_KEY,
)
class AuthNegativeSweepTests(APITestCase):
    """The behavioral half: real HTTP requests, real responses."""

    def setUp(self):
        # A real, authenticated user with zero scope Group memberships —
        # exactly the shape that would have slipped past Phase 12 finding
        # #1's pre-fix `permission_classes = [IsAuthenticated]`.
        self.no_scope_user = User.objects.create_user('sweep-no-scope-operator', password='pw')
        self.no_scope_token = issue_access_token(self.no_scope_user)['access_token']

    def _no_scope_auth_header(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.no_scope_token}'}

    def _call(self, entry, **headers):
        method = getattr(self.client, entry['method'])
        return method(entry['url'], **headers)

    def test_scoped_and_authenticated_endpoints_reject_unauthenticated_requests(self):
        entries = [e for e in ENDPOINT_REGISTRY if e['kind'] in ('scoped', 'authenticated_only')]
        self.assertGreater(len(entries), 0)  # sanity: the registry isn't empty
        for entry in entries:
            with self.subTest(view=entry['view'].__name__, method=entry['method'], url=entry['url']):
                response = self._call(entry)
                self.assertEqual(
                    response.status_code,
                    401,
                    f"{entry['view'].__name__} ({entry['method'].upper()} {entry['url']}) "
                    f'must reject an unauthenticated request with 401, got {response.status_code}',
                )

    def test_scoped_endpoints_reject_authenticated_requests_with_no_scope(self):
        entries = [e for e in ENDPOINT_REGISTRY if e['kind'] == 'scoped']
        self.assertGreater(len(entries), 0)
        for entry in entries:
            with self.subTest(view=entry['view'].__name__, method=entry['method'], url=entry['url']):
                response = self._call(entry, **self._no_scope_auth_header())
                self.assertEqual(
                    response.status_code,
                    403,
                    f"{entry['view'].__name__} ({entry['method'].upper()} {entry['url']}) "
                    f'must reject a no-scope authenticated request with 403 (this is the exact shape of '
                    f'Phase 12 finding #1: an authenticated user with no scope Groups reading a view that '
                    f'forgot its scope permission), got {response.status_code}',
                )

    def test_internal_key_endpoints_reject_requests_missing_the_service_key(self):
        entries = [e for e in ENDPOINT_REGISTRY if e['kind'] == 'internal_key']
        self.assertGreater(len(entries), 0)
        for entry in entries:
            with self.subTest(view=entry['view'].__name__, method=entry['method'], url=entry['url']):
                response = self._call(entry)
                self.assertEqual(
                    response.status_code,
                    403,
                    f"{entry['view'].__name__} ({entry['method'].upper()} {entry['url']}) "
                    f'must reject a request with no X-Internal-Service-Key header with 403, '
                    f'got {response.status_code}',
                )

    def test_internal_key_endpoints_reject_the_wrong_service_key(self):
        entries = [e for e in ENDPOINT_REGISTRY if e['kind'] == 'internal_key']
        for entry in entries:
            with self.subTest(view=entry['view'].__name__, method=entry['method'], url=entry['url']):
                response = self._call(entry, HTTP_X_INTERNAL_SERVICE_KEY='definitely-the-wrong-key')
                self.assertEqual(response.status_code, 403)
