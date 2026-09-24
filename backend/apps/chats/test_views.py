from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.chats.models import Chat, Contact, MediaReference, Message
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class ChatsApiTestCase(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')

    def _token_for(self, user):
        return issue_access_token(user)['access_token']

    def _auth_header(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {self._token_for(user)}'}

    def _reading_user(self, username='operator'):
        """A user whose issued JWT carries the 'reading' scope, via
        Group membership — the same mechanism apps.authn.jwt_utils.compute_scopes()
        already uses for ordinary (non-superuser) accounts."""
        user = User.objects.create_user(username, password='pw')
        group, _ = Group.objects.get_or_create(name='reading')
        user.groups.add(group)
        return user

    def _no_scope_user(self, username='noscope'):
        return User.objects.create_user(username, password='pw')


class ChatListViewTests(ChatsApiTestCase):
    URL = '/api/chats/'

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_reading_scope_is_forbidden(self):
        user = self._no_scope_user()
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_empty_dataset_returns_empty_page(self):
        user = self._reading_user()
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])
        self.assertEqual(response.data['count'], 0)

    def test_orders_most_recently_active_chat_first_nulls_last(self):
        user = self._reading_user()
        now = timezone.now()
        chat_no_messages = Chat.objects.create(session=self.session, provider_chat_id='c-none')
        chat_older = Chat.objects.create(
            session=self.session, provider_chat_id='c-older', last_message_at=now - timedelta(hours=2)
        )
        chat_newest = Chat.objects.create(
            session=self.session, provider_chat_id='c-newest', last_message_at=now
        )

        response = self.client.get(self.URL, **self._auth_header(user))
        ids_in_order = [row['provider_chat_id'] for row in response.data['results']]
        self.assertEqual(ids_in_order, ['c-newest', 'c-older', 'c-none'])
        # Sanity: every created chat actually appears (nulls_last, not dropped).
        self.assertIn(chat_no_messages.provider_chat_id, ids_in_order)
        self.assertIn(chat_older.provider_chat_id, ids_in_order)
        self.assertIn(chat_newest.provider_chat_id, ids_in_order)

    def test_reports_contact_name_via_select_related_no_n_plus_one(self):
        user = self._reading_user()
        for i in range(3):
            contact = Contact.objects.create(
                session=self.session, provider_contact_id=f'ct-{i}', display_name=f'Contact {i}'
            )
            Chat.objects.create(
                session=self.session, provider_chat_id=f'c-{i}', contact=contact, last_message_at=timezone.now()
            )

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(len(response.data['results']), 3)
        self.assertTrue(all(row['contact_name'] for row in response.data['results']))
        # Exactly 2 queries against chats_chat regardless of row count:
        # PageNumberPagination's own COUNT(*) plus the single page SELECT
        # (select_related folds the contact join into that same SELECT) —
        # never a third, per-row query.
        chat_queries = [q for q in ctx.captured_queries if 'chats_chat' in q['sql']]
        self.assertEqual(len(chat_queries), 2)

    def test_reports_phone_number_from_contact(self):
        # docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md Option 3 —
        # display-identity fallback, no new query (same select_related as
        # contact_name).
        user = self._reading_user()
        contact = Contact.objects.create(
            session=self.session, provider_contact_id='ct-1', phone_number='62811520892'
        )
        Chat.objects.create(
            session=self.session, provider_chat_id='c-1', contact=contact, last_message_at=timezone.now()
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(response.data['results'][0]['phone_number'], '62811520892')

    def test_phone_number_is_null_when_contact_has_none(self):
        user = self._reading_user()
        contact = Contact.objects.create(session=self.session, provider_contact_id='ct-1')
        Chat.objects.create(
            session=self.session, provider_chat_id='c-1', contact=contact, last_message_at=timezone.now()
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertIsNone(response.data['results'][0]['phone_number'])

    def test_phone_number_is_null_when_no_contact_linked(self):
        user = self._reading_user()
        Chat.objects.create(session=self.session, provider_chat_id='c-1', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertIsNone(response.data['results'][0]['phone_number'])

    def test_unread_true_when_never_read_and_has_a_message(self):
        user = self._reading_user()
        Chat.objects.create(session=self.session, provider_chat_id='c-1', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertTrue(response.data['results'][0]['unread'])

    def test_unread_false_when_read_after_last_message(self):
        user = self._reading_user()
        now = timezone.now()
        Chat.objects.create(
            session=self.session,
            provider_chat_id='c-1',
            last_message_at=now - timedelta(minutes=5),
            last_read_at=now,
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertFalse(response.data['results'][0]['unread'])

    def test_unread_true_when_new_message_arrived_after_last_read(self):
        user = self._reading_user()
        now = timezone.now()
        Chat.objects.create(
            session=self.session,
            provider_chat_id='c-1',
            last_message_at=now,
            last_read_at=now - timedelta(minutes=5),
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertTrue(response.data['results'][0]['unread'])

    def test_unread_false_for_a_chat_with_no_messages_yet(self):
        user = self._reading_user()
        Chat.objects.create(session=self.session, provider_chat_id='c-1')
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertFalse(response.data['results'][0]['unread'])

    def test_pagination_respects_page_size(self):
        user = self._reading_user()
        for i in range(25):
            Chat.objects.create(session=self.session, provider_chat_id=f'c-{i}', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['count'], 25)
        self.assertIsNotNone(response.data['next'])


class ChatMessagesViewTests(ChatsApiTestCase):
    def setUp(self):
        super().setUp()
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='c-1')

    def _url(self, chat_id=None):
        return f'/api/chats/{chat_id or self.chat.pk}/messages/'

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_unknown_chat_returns_404(self):
        user = self._reading_user()
        response = self.client.get(self._url(chat_id=999999), **self._auth_header(user))
        self.assertEqual(response.status_code, 404)

    def test_empty_history_returns_empty_page(self):
        user = self._reading_user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_ordered_newest_first_deterministic_on_tied_timestamps(self):
        user = self._reading_user()
        ts = timezone.now()
        # Same timestamp for both — ordering must still be deterministic
        # (secondary sort key), not "whatever the DB feels like".
        older_pk_first = Message.objects.create(
            session=self.session, chat=self.chat, provider_message_id='m1',
            direction=Message.DIRECTION_INBOUND, timestamp=ts,
        )
        newer_pk_second = Message.objects.create(
            session=self.session, chat=self.chat, provider_message_id='m2',
            direction=Message.DIRECTION_INBOUND, timestamp=ts,
        )

        response = self.client.get(self._url(), **self._auth_header(user))
        ids = [row['id'] for row in response.data['results']]
        self.assertEqual(ids, [newer_pk_second.pk, older_pk_first.pk])

    def test_includes_media_without_n_plus_one(self):
        user = self._reading_user()
        message = Message.objects.create(
            session=self.session, chat=self.chat, provider_message_id='m1',
            direction=Message.DIRECTION_INBOUND, timestamp=timezone.now(),
        )
        MediaReference.objects.create(message=message, file_name='photo.jpg', mime_type='image/jpeg')

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['results'][0]['media'][0]['file_name'], 'photo.jpg')
        self.assertNotIn('storage_reference', response.data['results'][0]['media'][0])
        media_queries = [q for q in ctx.captured_queries if 'chats_mediareference' in q['sql']]
        self.assertEqual(len(media_queries), 1)

    def test_pagination_bounded(self):
        user = self._reading_user()
        for i in range(25):
            Message.objects.create(
                session=self.session, chat=self.chat, provider_message_id=f'm{i}',
                direction=Message.DIRECTION_INBOUND, timestamp=timezone.now(),
            )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['count'], 25)


class ChatMarkReadViewTests(ChatsApiTestCase):
    def setUp(self):
        super().setUp()
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='c-1')

    def _url(self, chat_id=None):
        return f'/api/chats/{chat_id or self.chat.pk}/read/'

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 401)

    def test_without_reading_scope_is_forbidden(self):
        user = self._no_scope_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_unknown_chat_returns_404(self):
        user = self._reading_user()
        response = self.client.post(self._url(chat_id=999999), **self._auth_header(user))
        self.assertEqual(response.status_code, 404)

    def test_sets_last_read_at_to_now(self):
        user = self._reading_user()
        self.assertIsNone(self.chat.last_read_at)
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.chat.refresh_from_db()
        self.assertIsNotNone(self.chat.last_read_at)

    def test_marking_read_flips_unread_to_false_on_the_list_endpoint(self):
        user = self._reading_user()
        self.chat.last_message_at = timezone.now()
        self.chat.save(update_fields=['last_message_at'])

        before = self.client.get('/api/chats/', **self._auth_header(user))
        self.assertTrue(before.data['results'][0]['unread'])

        self.client.post(self._url(), **self._auth_header(user))

        after = self.client.get('/api/chats/', **self._auth_header(user))
        self.assertFalse(after.data['results'][0]['unread'])
