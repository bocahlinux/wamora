import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('waha_monitoring')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@app.on_after_configure.connect
def _setup_periodic_tasks(sender, **kwargs):
    """Schedules periodic reconciliation (docs/05-WEBHOOK-SYNC-DESIGN.md:
    "reconciliation job" — the only recurring job documented anywhere in
    this project; Celery beat was provisioned specifically for this, see
    docs/00-MASTER-SPEC.md). Deferred into a signal handler (rather than a
    plain app.conf.beat_schedule assignment above) so it reads
    settings.RECONCILIATION_INTERVAL_SECONDS through Django's settings
    object at configure time, after config_from_object has run.
    """
    from django.conf import settings

    sender.add_periodic_task(
        settings.RECONCILIATION_INTERVAL_SECONDS,
        app.signature('apps.sync.tasks.reconcile_all_sessions_task'),
        name='reconcile-all-sessions',
    )

    # Conversation Engine — auto-expires a WAITING_OPERATOR
    # ConversationSession nobody manually closed within
    # settings.CONVERSATION_WAITING_OPERATOR_TIMEOUT_SECONDS (default 24h).
    # See apps.chats.tasks's own docstring.
    sender.add_periodic_task(
        settings.CONVERSATION_EXPIRY_SCAN_INTERVAL_SECONDS,
        app.signature('apps.chats.tasks.expire_waiting_operator_sessions_task'),
        name='expire-waiting-operator-sessions',
    )
