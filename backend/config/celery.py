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
