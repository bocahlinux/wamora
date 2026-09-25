import copy

from django.test import TestCase
from django.utils import timezone

from apps.chats.models import Chat, Contact, Message
from apps.sync.models import SyncCheckpoint
from apps.sync.reconciliation import reconcile_session
from apps.sync.tests.fixtures import (
    REST_INBOUND_MESSAGE_1,
    REST_INBOUND_MESSAGE_2,
    REST_OUTBOUND_MESSAGE_OTHER_CHAT,
    REST_OUTBOUND_MESSAGE_SAME_CHAT,
    make_message,
)
from apps.sync.waha_client import WahaClientError
from apps.waha_sessions.models import WahaSession
from apps.webhooks.parsing import parse_envelope
from apps.webhooks.services import ingest_webhook


class StubWahaClient:
    """Test double simulating real confirmed WAHA pagination behavior:
    `messages_by_chat[chat_id]` is the FULL newest-first ordered history for
    that chat; `fetch_chat_messages` slices it by limit/offset exactly like
    the real deployment does (no overlap, no gap). Short lists (<= limit)
    behave exactly like the old single-page stub, so existing tests are
    unaffected."""

    def __init__(self, messages_by_chat=None, failing_chats=None, fail_after_calls=None, chats=None, chats_error=None):
        self.messages_by_chat = messages_by_chat or {}
        self.failing_chats = failing_chats or set()
        # chat_id -> number of successful calls to allow before raising —
        # simulates a failure partway through a multi-page fetch.
        self.fail_after_calls = fail_after_calls or {}
        self.calls = []
        self._calls_per_chat = {}
        # Inbox/Chat chat-discovery (docs/generated/INBOX-CHAT-DECISION-REPORT.md
        # Section 4) — `chats` is the raw WAHA chat-list response to return;
        # empty by default so every existing message-reconciliation test is
        # unaffected (discovery finds nothing, discovers nothing).
        self.chats = chats if chats is not None else []
        self.chats_error = chats_error
        self.fetch_chats_calls = []

    def fetch_chats(self, session):
        self.fetch_chats_calls.append(session)
        if self.chats_error is not None:
            raise WahaClientError(self.chats_error)
        return self.chats

    def fetch_chat_messages(self, session, chat_id, limit=100, offset=0):
        self.calls.append((session, chat_id, limit, offset))
        if chat_id in self.failing_chats:
            raise WahaClientError('simulated failure')

        self._calls_per_chat[chat_id] = self._calls_per_chat.get(chat_id, 0) + 1
        if chat_id in self.fail_after_calls and self._calls_per_chat[chat_id] > self.fail_after_calls[chat_id]:
            raise WahaClientError('simulated failure mid-pagination')

        full_history = self.messages_by_chat.get(chat_id, [])
        return full_history[offset:offset + limit]


def _seed_chat(session, provider_chat_id):
    return Chat.objects.create(session=session, provider_chat_id=provider_chat_id)


class ReconciliationBasicTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        self.chat = _seed_chat(self.session, '000000000000000@lid')

    def test_missing_message_is_inserted(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.messages_inserted, 1)
        self.assertTrue(
            Message.objects.filter(
                session=self.session,
                provider_message_id='false_000000000000000@lid_2A19C241A2D8A0CD88E6',
            ).exists()
        )

    def test_existing_message_is_not_duplicated(self):
        Message.objects.create(
            session=self.session,
            chat=self.chat,
            provider_message_id='false_000000000000000@lid_2A19C241A2D8A0CD88E6',
            direction=Message.DIRECTION_INBOUND,
            body='Halo pak',
            timestamp=timezone.now(),
        )
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.messages_inserted, 0)
        self.assertEqual(result.messages_skipped_existing, 1)
        self.assertEqual(
            Message.objects.filter(provider_message_id='false_000000000000000@lid_2A19C241A2D8A0CD88E6').count(), 1
        )

    def test_rerunning_reconciliation_is_idempotent(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1, REST_INBOUND_MESSAGE_2]})
        reconcile_session('test_session', waha_client=client)
        result2 = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result2.messages_inserted, 0)
        self.assertEqual(result2.messages_skipped_existing, 2)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)

    def test_provider_message_id_preserved_exactly(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)
        message = Message.objects.get(session=self.session)
        self.assertEqual(message.provider_message_id, REST_INBOUND_MESSAGE_1['id'])

    def test_info_id_is_not_substituted_for_messages_id(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)
        message = Message.objects.get(session=self.session)
        info_id = REST_INBOUND_MESSAGE_1['_data']['Info']['ID']
        self.assertNotEqual(message.provider_message_id, info_id)
        self.assertEqual(message.provider_message_id, REST_INBOUND_MESSAGE_1['id'])

    def test_lid_identifier_preserved_verbatim(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)
        chat = Chat.objects.get(session=self.session, provider_chat_id='000000000000000@lid')
        contact = Contact.objects.get(session=self.session)
        self.assertEqual(chat.provider_chat_id, '000000000000000@lid')
        self.assertEqual(contact.provider_contact_id, '000000000000000@lid')

    def test_phone_number_not_used_as_identity_key(self):
        # Same phone number appears as SenderAlt here and as the primary
        # Chat identity of REST_OUTBOUND_MESSAGE_OTHER_CHAT — reconciliation
        # must not merge them.
        other_chat = _seed_chat(self.session, '62800000000@s.whatsapp.net')
        client = StubWahaClient(
            {
                '000000000000000@lid': [REST_INBOUND_MESSAGE_1],
                '62800000000@s.whatsapp.net': [REST_OUTBOUND_MESSAGE_OTHER_CHAT],
            }
        )
        reconcile_session('test_session', waha_client=client)

        self.assertEqual(Chat.objects.filter(session=self.session).count(), 2)
        lid_contact = Contact.objects.get(session=self.session, provider_contact_id='000000000000000@lid')
        self.assertEqual(lid_contact.phone_number, '62800000000')
        # The other chat's outbound-only traffic creates no Contact at all
        # (see outbound test below) — confirming no merge occurred.
        self.assertEqual(Contact.objects.filter(session=self.session).count(), 1)

    def test_outbound_message_does_not_create_contact_from_sender(self):
        client = StubWahaClient({'000000000000000@lid': [REST_OUTBOUND_MESSAGE_SAME_CHAT]})
        reconcile_session('test_session', waha_client=client)

        self.assertEqual(Contact.objects.filter(session=self.session).count(), 0)
        message = Message.objects.get(session=self.session)
        self.assertEqual(message.direction, Message.DIRECTION_OUTBOUND)


class ReconciliationScopeTests(TestCase):
    def test_only_processes_already_known_chats(self):
        session = WahaSession.objects.create(name='test_session')
        _seed_chat(session, '000000000000000@lid')
        # A chat WAHA might report but that isn't already known locally
        # must never be fetched — reconciliation is bounded, not a full
        # account discovery/sync (docs' "do not implement mass
        # synchronization blindly").
        client = StubWahaClient({'unknown-chat@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)

        fetched_chat_ids = {call[1] for call in client.calls}
        self.assertEqual(fetched_chat_ids, {'000000000000000@lid'})

    def test_chat_ids_filter_narrows_scope(self):
        session = WahaSession.objects.create(name='test_session')
        _seed_chat(session, 'chat-a@lid')
        _seed_chat(session, 'chat-b@lid')
        client = StubWahaClient({'chat-a@lid': [], 'chat-b@lid': []})
        reconcile_session('test_session', chat_ids=['chat-a@lid'], waha_client=client)

        fetched_chat_ids = {call[1] for call in client.calls}
        self.assertEqual(fetched_chat_ids, {'chat-a@lid'})

    def test_single_call_per_chat_per_run_no_pagination_loop(self):
        session = WahaSession.objects.create(name='test_session')
        _seed_chat(session, '000000000000000@lid')
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)

        self.assertEqual(len(client.calls), 1)


class ReconciliationSessionScopingTests(TestCase):
    def test_same_message_id_in_different_sessions_remains_valid(self):
        session_a = WahaSession.objects.create(name='session-a')
        session_b = WahaSession.objects.create(name='session-b')
        _seed_chat(session_a, '000000000000000@lid')
        _seed_chat(session_b, '000000000000000@lid')

        client_a = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        client_b = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('session-a', waha_client=client_a)
        reconcile_session('session-b', waha_client=client_b)

        self.assertEqual(
            Message.objects.filter(provider_message_id=REST_INBOUND_MESSAGE_1['id']).count(), 2
        )

    def test_chat_identity_is_session_scoped(self):
        session_a = WahaSession.objects.create(name='session-a')
        session_b = WahaSession.objects.create(name='session-b')
        _seed_chat(session_a, 'shared-id@lid')
        _seed_chat(session_b, 'shared-id@lid')
        self.assertEqual(Chat.objects.filter(provider_chat_id='shared-id@lid').count(), 2)

    def test_contact_identity_is_session_scoped(self):
        session_a = WahaSession.objects.create(name='session-a')
        session_b = WahaSession.objects.create(name='session-b')
        _seed_chat(session_a, '000000000000000@lid')
        _seed_chat(session_b, '000000000000000@lid')
        client_a = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        client_b = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('session-a', waha_client=client_a)
        reconcile_session('session-b', waha_client=client_b)

        self.assertEqual(Contact.objects.filter(provider_contact_id='000000000000000@lid').count(), 2)


class ReconciliationCheckpointTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        _seed_chat(self.session, '000000000000000@lid')

    def test_successful_run_advances_checkpoint_to_latest_timestamp(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1, REST_INBOUND_MESSAGE_2]})
        reconcile_session('test_session', waha_client=client)

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_OK)
        self.assertNotEqual(checkpoint.checkpoint_value, '')
        self.assertIsNotNone(checkpoint.last_run_at)
        self.assertEqual(checkpoint.last_error, '')

    def test_failed_fetch_does_not_advance_checkpoint(self):
        client = StubWahaClient(failing_chats={'000000000000000@lid'})
        reconcile_session('test_session', waha_client=client)

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)
        self.assertEqual(checkpoint.checkpoint_value, '')  # never advanced
        self.assertNotEqual(checkpoint.last_error, '')
        self.assertIsNotNone(checkpoint.last_run_at)  # still recorded

    def test_error_does_not_falsely_mark_success_and_retry_recovers(self):
        failing_client = StubWahaClient(failing_chats={'000000000000000@lid'})
        reconcile_session('test_session', waha_client=failing_client)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)

        working_client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        result = reconcile_session('test_session', waha_client=working_client)

        self.assertFalse(result.had_error)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_OK)
        self.assertNotEqual(checkpoint.checkpoint_value, '')

    def test_partial_message_parse_failure_marks_run_as_error(self):
        broken_message = copy.deepcopy(REST_INBOUND_MESSAGE_1)
        del broken_message['id']
        client = StubWahaClient({'000000000000000@lid': [broken_message]})
        result = reconcile_session('test_session', waha_client=client)

        self.assertTrue(result.had_error)
        self.assertEqual(result.messages_failed, 1)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)
        self.assertEqual(checkpoint.checkpoint_value, '')

    # -- trigger_source / task_id (this task) -------------------------------
    # docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-IMPLEMENTATION-REPORT.md.
    # Purely additive metadata — never affects Message/Chat/Contact
    # persistence or checkpoint_value/status semantics (already proven
    # unchanged by every other test in this class, none of which passes
    # these new parameters).

    def test_trigger_source_and_task_id_are_recorded_when_passed(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session(
            'test_session', waha_client=client,
            trigger_source=SyncCheckpoint.TRIGGER_PERIODIC, task_id='abc-123',
        )
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_PERIODIC)
        self.assertEqual(checkpoint.last_run_task_id, 'abc-123')

    def test_empty_task_id_clears_a_previously_recorded_one(self):
        # A 'targeted' run via the sync executor explicitly passes
        # task_id='' — this must overwrite (not preserve) a stale task_id
        # left by an earlier, different run for the same session.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session(
            'test_session', waha_client=client,
            trigger_source=SyncCheckpoint.TRIGGER_PERIODIC, task_id='stale-id',
        )
        reconcile_session(
            'test_session', chat_ids=['000000000000000@lid'], waha_client=client,
            trigger_source=SyncCheckpoint.TRIGGER_TARGETED, task_id='',
        )
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_TARGETED)
        self.assertEqual(checkpoint.last_run_task_id, '')

    def test_trigger_source_and_task_id_default_to_blank_when_not_passed(self):
        # Backward compatibility: every pre-existing call site/test in this
        # file that doesn't pass these new parameters must keep working
        # unchanged — the fields simply stay at the model's own blank
        # default, never populated with an invented value.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, '')
        self.assertEqual(checkpoint.last_run_task_id, '')

    def test_trigger_metadata_survives_to_a_failed_run_too(self):
        # Recorded at the START of the run (write A) — still present even
        # if the run ends in STATUS_ERROR, not only on success.
        client = StubWahaClient(failing_chats={'000000000000000@lid'})
        reconcile_session(
            'test_session', waha_client=client,
            trigger_source=SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND, task_id='',
        )
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND)

    def test_trigger_metadata_does_not_affect_checkpoint_value_or_messages(self):
        # Same assertions test_successful_run_advances_checkpoint_to_latest_timestamp
        # already makes, now also passing trigger_source/task_id — proves
        # the new parameters don't change this existing behavior at all.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1, REST_INBOUND_MESSAGE_2]})
        reconcile_session(
            'test_session', waha_client=client,
            trigger_source=SyncCheckpoint.TRIGGER_PERIODIC, task_id='xyz',
        )
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_OK)
        self.assertNotEqual(checkpoint.checkpoint_value, '')
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)


class ReconciliationCrossPathConsistencyTests(TestCase):
    """REST parsing and webhook parsing must not contradict each other for
    the confirmed fields — same message, same result, regardless of path."""

    def test_webhook_then_reconciliation_recognizes_same_message_as_existing(self):
        session = WahaSession.objects.create(name='test_session')
        _seed_chat(session, '000000000000000@lid')

        webhook_envelope = {
            'event': 'message',
            'session': 'test_session',
            'payload': REST_INBOUND_MESSAGE_1,
        }
        ingest_webhook(parse_envelope(webhook_envelope))
        self.assertEqual(Message.objects.count(), 1)

        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.messages_inserted, 0)
        self.assertEqual(result.messages_skipped_existing, 1)
        self.assertEqual(Message.objects.count(), 1)

    def test_reconciliation_then_webhook_recognizes_same_message_as_duplicate(self):
        session = WahaSession.objects.create(name='test_session')
        _seed_chat(session, '000000000000000@lid')

        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('test_session', waha_client=client)
        self.assertEqual(Message.objects.count(), 1)

        webhook_envelope = {
            'event': 'message',
            'session': 'test_session',
            'payload': REST_INBOUND_MESSAGE_1,
        }
        webhook_event = ingest_webhook(parse_envelope(webhook_envelope))

        from apps.webhooks.models import WebhookEvent

        self.assertEqual(webhook_event.status, WebhookEvent.STATUS_PROCESSED)
        self.assertEqual(Message.objects.count(), 1)

    def test_resulting_message_row_identical_regardless_of_path(self):
        session_webhook = WahaSession.objects.create(name='session-webhook')
        session_reconcile = WahaSession.objects.create(name='session-reconcile')
        _seed_chat(session_reconcile, '000000000000000@lid')

        ingest_webhook(
            parse_envelope({'event': 'message', 'session': 'session-webhook', 'payload': REST_INBOUND_MESSAGE_1})
        )
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        reconcile_session('session-reconcile', waha_client=client)

        m1 = Message.objects.get(session=session_webhook)
        m2 = Message.objects.get(session=session_reconcile)
        self.assertEqual(m1.provider_message_id, m2.provider_message_id)
        self.assertEqual(m1.direction, m2.direction)
        self.assertEqual(m1.body, m2.body)
        self.assertEqual(m1.timestamp, m2.timestamp)


def _newest_first_history(count, chat_id='000000000000000@lid'):
    """Builds a synthetic newest-first history of `count` messages,
    matching the confirmed real ordering (docs/generated/PHASE-4-RECONCILIATION.md)."""
    return [make_message(seq, chat_id=chat_id) for seq in range(count, 0, -1)]


class ReconciliationPaginationTests(TestCase):
    """Pagination confirmed against the real deployed WAHA instance:
    limit+offset slice correctly with no overlap/gap, newest-first
    ordering, `page` param does not work (never sent)."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        self.chat = _seed_chat(self.session, '000000000000000@lid')

    def test_first_page_uses_offset_zero(self):
        history = _newest_first_history(5)
        client = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=2, waha_client=client)

        first_call = client.calls[0]
        self.assertEqual(first_call[2:], (2, 0))  # (limit, offset)

    def test_second_page_uses_correct_offset(self):
        history = _newest_first_history(5)
        client = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=2, waha_client=client)

        offsets_used = [call[3] for call in client.calls]
        self.assertEqual(offsets_used, [0, 2, 4])  # 5 messages, limit 2 -> 3 pages

    def test_all_pages_are_inserted(self):
        history = _newest_first_history(5)
        client = StubWahaClient({'000000000000000@lid': history})
        result = reconcile_session('test_session', limit=2, waha_client=client)

        self.assertEqual(result.messages_inserted, 5)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 5)

    def test_stops_when_a_page_is_shorter_than_limit(self):
        history = _newest_first_history(5)  # not a multiple of limit=3
        client = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=3, waha_client=client)

        # page 1: offset 0 (3 items, full) -> continue
        # page 2: offset 3 (2 items, short) -> stop, no page 3
        self.assertEqual(len(client.calls), 2)

    def test_empty_first_page_makes_no_further_calls(self):
        client = StubWahaClient({'000000000000000@lid': []})
        result = reconcile_session('test_session', limit=10, waha_client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.messages_inserted, 0)
        self.assertFalse(result.had_error)

    def test_partial_last_page_all_messages_still_inserted(self):
        history = _newest_first_history(7)
        client = StubWahaClient({'000000000000000@lid': history})
        result = reconcile_session('test_session', limit=5, waha_client=client)

        # page 1: 5 items (full) -> continue; page 2: 2 items (partial) -> stop
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result.messages_inserted, 7)

    def test_max_pages_caps_fetching_bounded_not_unlimited(self):
        history = _newest_first_history(50)
        client = StubWahaClient({'000000000000000@lid': history})
        result = reconcile_session('test_session', limit=5, max_pages=3, waha_client=client)

        self.assertEqual(len(client.calls), 3)  # never exceeds max_pages
        self.assertEqual(result.messages_inserted, 15)  # 3 pages * 5, not all 50

    def test_stops_at_checkpoint_watermark_boundary(self):
        # First run: sync everything, establishing a watermark.
        history = _newest_first_history(6)
        client1 = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=2, waha_client=client1)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 6)

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        watermark_before = checkpoint.checkpoint_value
        self.assertNotEqual(watermark_before, '')

        # Second run: 2 brand-new newer messages (seq 7, 8) prepended,
        # rest unchanged. Reconciliation should stop once it reaches
        # messages at/before the watermark rather than re-walking all 8.
        newer = [make_message(8), make_message(7)]
        full_history = newer + history
        client2 = StubWahaClient({'000000000000000@lid': full_history})
        result = reconcile_session('test_session', limit=2, waha_client=client2)

        self.assertEqual(result.messages_inserted, 2)  # only the 2 new ones
        # Should stop after the page containing the watermark boundary —
        # far fewer calls than would be needed to re-walk all 8 messages.
        self.assertLessEqual(len(client2.calls), 4)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 8)

    def test_rerunning_paginated_reconciliation_is_idempotent(self):
        history = _newest_first_history(6)
        client1 = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=2, waha_client=client1)

        client2 = StubWahaClient({'000000000000000@lid': history})
        result2 = reconcile_session('test_session', limit=2, waha_client=client2)

        self.assertEqual(result2.messages_inserted, 0)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 6)

    def test_duplicate_ids_across_pages_not_duplicated(self):
        # Defensive: if WAHA ever returned overlapping pages (not observed,
        # but not something to trust blindly either), the DB constraint
        # must still prevent a duplicate — simulate by repeating one
        # message across two "pages" via a client that ignores offset.
        overlapping_msg = make_message(1)

        class OverlappingStubClient:
            def __init__(self):
                self.call_count = 0

            def fetch_chats(self, session):
                return []

            def fetch_chat_messages(self, session, chat_id, limit=100, offset=0):
                self.call_count += 1
                if self.call_count == 1:
                    return [overlapping_msg, make_message(2)]
                if self.call_count == 2:
                    return [overlapping_msg]  # duplicate, wrong client behavior
                return []

        result = reconcile_session('test_session', limit=2, waha_client=OverlappingStubClient())
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)
        self.assertGreaterEqual(result.messages_skipped_existing, 0)  # dedup absorbed it silently

    def test_offset_is_never_written_to_checkpoint_value(self):
        history = _newest_first_history(5)
        client = StubWahaClient({'000000000000000@lid': history})
        reconcile_session('test_session', limit=2, waha_client=client)

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        # checkpoint_value must be a timestamp (parseable ISO datetime),
        # never a raw pagination offset integer.
        import datetime

        datetime.datetime.fromisoformat(checkpoint.checkpoint_value)  # raises if not a valid timestamp

    def test_failure_mid_pagination_preserves_inserted_messages_but_marks_error(self):
        history = _newest_first_history(6)
        client = StubWahaClient({'000000000000000@lid': history}, fail_after_calls={'000000000000000@lid': 1})
        result = reconcile_session('test_session', limit=2, waha_client=client)

        self.assertTrue(result.had_error)
        # First page succeeded and was persisted before the second page failed.
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)
        self.assertEqual(checkpoint.checkpoint_value, '')  # not advanced despite partial progress


class ReconciliationChatDiscoveryTests(TestCase):
    """Inbox/Chat (canonical Phase 8) chat discovery —
    docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 4."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')

    def test_creates_a_chat_row_waha_reports_that_django_has_never_seen(self):
        client = StubWahaClient(chats=[{'id': 'new-chat@lid'}])
        self.assertEqual(Chat.objects.filter(session=self.session).count(), 0)

        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.chats_discovered, 1)
        self.assertTrue(Chat.objects.filter(session=self.session, provider_chat_id='new-chat@lid').exists())

    def test_prefers_nested_info_chat_over_top_level_id(self):
        client = StubWahaClient(chats=[{'id': 'wrong@lid', '_data': {'Info': {'Chat': 'right@lid'}}}])
        reconcile_session('test_session', waha_client=client)
        self.assertTrue(Chat.objects.filter(session=self.session, provider_chat_id='right@lid').exists())
        self.assertFalse(Chat.objects.filter(session=self.session, provider_chat_id='wrong@lid').exists())

    def test_does_not_duplicate_an_already_known_chat(self):
        _seed_chat(self.session, 'existing@lid')
        client = StubWahaClient(chats=[{'id': 'existing@lid'}])

        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.chats_discovered, 0)
        self.assertEqual(Chat.objects.filter(session=self.session, provider_chat_id='existing@lid').count(), 1)

    def test_skips_an_entry_with_no_usable_identifier_without_crashing(self):
        client = StubWahaClient(chats=[{'name': 'no id field here'}, {'id': 'good@lid'}])
        result = reconcile_session('test_session', waha_client=client)
        self.assertEqual(result.chats_discovered, 1)
        self.assertTrue(Chat.objects.filter(session=self.session, provider_chat_id='good@lid').exists())

    def test_discovery_failure_is_reported_but_does_not_fail_the_whole_run(self):
        _seed_chat(self.session, 'existing@lid')
        client = StubWahaClient(
            messages_by_chat={'existing@lid': []},
            chats_error='simulated discovery failure',
        )

        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.chats_discovered, 0)
        self.assertEqual(result.chat_discovery_error, 'simulated discovery failure')
        # The pre-existing chat's own (empty) history reconciliation still
        # ran and succeeded — discovery failing is not fatal to the rest.
        self.assertFalse(result.had_error)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_OK)

    def test_a_targeted_chat_ids_run_does_not_trigger_discovery(self):
        chat = _seed_chat(self.session, 'existing@lid')
        client = StubWahaClient(
            messages_by_chat={'existing@lid': []},
            chats=[{'id': 'should-not-be-discovered@lid'}],
        )

        result = reconcile_session('test_session', chat_ids=[chat.provider_chat_id], waha_client=client)

        self.assertEqual(client.fetch_chats_calls, [])
        self.assertEqual(result.chats_discovered, 0)
        self.assertFalse(
            Chat.objects.filter(session=self.session, provider_chat_id='should-not-be-discovered@lid').exists()
        )

    def test_a_newly_discovered_chat_also_gets_its_message_history_reconciled_in_the_same_run(self):
        history = _newest_first_history(2)
        client = StubWahaClient(
            chats=[{'id': '000000000000000@lid'}],
            messages_by_chat={'000000000000000@lid': history},
        )

        result = reconcile_session('test_session', waha_client=client)

        self.assertEqual(result.chats_discovered, 1)
        self.assertEqual(result.messages_inserted, 2)
        self.assertEqual(Message.objects.filter(session=self.session).count(), 2)
