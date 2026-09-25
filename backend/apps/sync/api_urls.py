"""Frontend-facing (JWT-authenticated) URLs for apps.sync — Phase 9.1A.

Deliberately a separate module from `urls.py` (which is committed to the
`/internal/` prefix's HasInternalServiceKey semantics — see
`internal_views.py`'s own docstring) and mounted at a different prefix
(`api/sync/`, see `config/urls.py`) so the two trust boundaries never
share a URL namespace.
"""

from django.urls import path

from .views import SyncCheckpointRecoveryView, SyncCheckpointTaskStateView, SyncStatusView

urlpatterns = [
    path('status/<str:session_name>/', SyncStatusView.as_view(), name='sync-status'),
    # Phase 13.A — manual recovery only. See SyncCheckpointRecoveryView's
    # own docstring for the full scope/safety contract.
    path('recover/<str:session_name>/', SyncCheckpointRecoveryView.as_view(), name='sync-recover'),
    # Diagnostic Celery task-state correlation only — never recovery. See
    # SyncCheckpointTaskStateView's own docstring for the full contract.
    path('task-state/<str:session_name>/', SyncCheckpointTaskStateView.as_view(), name='sync-task-state'),
]
