from django.core.management.base import BaseCommand, CommandError

from apps.sync.models import SyncCheckpoint
from apps.sync.reconciliation import reconcile_session
from apps.waha_sessions.models import WahaSession


class Command(BaseCommand):
    help = 'Reconcile a WAHA session\'s known chats against WAHA REST history.'

    def add_arguments(self, parser):
        parser.add_argument('session', help='WahaSession.name to reconcile')
        parser.add_argument(
            '--chat', action='append', dest='chat_ids', default=None,
            help='Limit to this provider_chat_id (repeatable). Default: all known chats for the session.',
        )
        parser.add_argument('--limit', type=int, default=100, help='Messages to fetch per page (default 100).')
        parser.add_argument(
            '--max-pages', type=int, default=10, dest='max_pages',
            help='Safety cap on pages fetched per chat per run (default 10).',
        )

    def handle(self, *args, **options):
        session_name = options['session']
        if not WahaSession.objects.filter(name=session_name).exists():
            raise CommandError(f'No WahaSession named "{session_name}" exists.')

        result = reconcile_session(
            session_name,
            chat_ids=options['chat_ids'],
            limit=options['limit'],
            max_pages=options['max_pages'],
            trigger_source=SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND,
            task_id='',
        )

        self.stdout.write(f'chats_processed={result.chats_processed}')
        self.stdout.write(f'messages_inserted={result.messages_inserted}')
        self.stdout.write(f'messages_skipped_existing={result.messages_skipped_existing}')
        self.stdout.write(f'messages_failed={result.messages_failed}')
        if result.had_error:
            self.stderr.write(self.style.ERROR('Reconciliation completed with errors:'))
            for err in result.chat_fetch_errors + result.message_errors:
                self.stderr.write(f'  - {err}')
        else:
            self.stdout.write(self.style.SUCCESS('Reconciliation completed successfully.'))
