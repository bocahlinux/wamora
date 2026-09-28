from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.chats.models import Chat, Contact, MediaReference, Message
from apps.offices.models import Office, OfficeMembership, ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Role
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

# Step 5 (Inbox <-> Office integration) — sentinel distinguishing "use the
# shared default Office" from an explicit `office=None` ("no membership at
# all"), the same idiom apps/blast/tests/test_views.py already uses for its
# own `_user`/`_create_campaign` helpers.
_DEFAULT_OFFICE = object()

# The Role merge — resolves the old CharField's three fixed string
# values to the migration-0009-seeded Role rows with the matching
# organizational flags, so the helpers below keep accepting the same
# ROLE_GLOBAL_ADMIN/ROLE_OFFICE_ADMIN/ROLE_OPERATOR constants every
# existing test call site already passes them.
def _seeded_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={
            'grants_global_access': name == ROLE_GLOBAL_ADMIN,
            'is_office_admin': name == ROLE_OFFICE_ADMIN,
            'is_operator': name == ROLE_OPERATOR,
        },
    )
    return role


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class ChatsApiTestCase(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        # A shared default Office so every pre-existing test (none of
        # which cared about Office boundaries before this step) keeps
        # working unchanged: the default reading user and the default
        # chat both land in the same Office (Step 5).
        self.office = Office.objects.create(name='Office A')

    def _token_for(self, user):
        return issue_access_token(user)['access_token']

    def _auth_header(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {self._token_for(user)}'}

    def _reading_user(self, username='operator', office=_DEFAULT_OFFICE, role=ROLE_OPERATOR):
        """A user whose issued JWT carries the 'reading' scope, via
        Group membership — the same mechanism apps.authn.jwt_utils.compute_scopes()
        already uses for ordinary (non-superuser) accounts.

        Also gets an `OfficeMembership` in `self.office` by default
        (Step 5) — pass `office=None` explicitly for a user with no
        Office membership at all, or `role=ROLE_GLOBAL_ADMIN` for a
        Global Admin (whose membership always has `office=None`
        regardless of what's passed here, per apps.offices' own
        office_matches_role constraint)."""
        user = User.objects.create_user(username, password='pw')
        group, _ = Group.objects.get_or_create(name='reading')
        user.groups.add(group)
        if role == ROLE_GLOBAL_ADMIN:
            OfficeMembership.objects.create(
                user=user, office=None, role=_seeded_role(ROLE_GLOBAL_ADMIN), requires_office=False
            )
        else:
            actual_office = self.office if office is _DEFAULT_OFFICE else office
            if actual_office is not None:
                role_obj = _seeded_role(role)
                OfficeMembership.objects.create(
                    user=user, office=actual_office, role=role_obj, requires_office=not role_obj.grants_global_access
                )
        return user

    def _no_scope_user(self, username='noscope'):
        return User.objects.create_user(username, password='pw')

    def _create_chat(self, **kwargs):
        """Same session/office defaults as `_reading_user`'s default
        Office, so a chat and its reader are in the same Office unless a
        test explicitly overrides one of them (Step 5)."""
        kwargs.setdefault('session', self.session)
        kwargs.setdefault('office', self.office)
        return Chat.objects.create(**kwargs)


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
        chat_no_messages = self._create_chat(provider_chat_id='c-none')
        chat_older = self._create_chat(
            provider_chat_id='c-older', last_message_at=now - timedelta(hours=2)
        )
        chat_newest = self._create_chat(
            provider_chat_id='c-newest', last_message_at=now
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
            self._create_chat(provider_chat_id=f'c-{i}', contact=contact, last_message_at=timezone.now())

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
        self._create_chat(provider_chat_id='c-1', contact=contact, last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(response.data['results'][0]['phone_number'], '62811520892')

    def test_phone_number_is_null_when_contact_has_none(self):
        user = self._reading_user()
        contact = Contact.objects.create(session=self.session, provider_contact_id='ct-1')
        self._create_chat(provider_chat_id='c-1', contact=contact, last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertIsNone(response.data['results'][0]['phone_number'])

    def test_phone_number_is_null_when_no_contact_linked(self):
        user = self._reading_user()
        self._create_chat(provider_chat_id='c-1', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertIsNone(response.data['results'][0]['phone_number'])

    def test_unread_true_when_never_read_and_has_a_message(self):
        user = self._reading_user()
        self._create_chat(provider_chat_id='c-1', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertTrue(response.data['results'][0]['unread'])

    def test_unread_false_when_read_after_last_message(self):
        user = self._reading_user()
        now = timezone.now()
        self._create_chat(
            provider_chat_id='c-1',
            last_message_at=now - timedelta(minutes=5),
            last_read_at=now,
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertFalse(response.data['results'][0]['unread'])

    def test_unread_true_when_new_message_arrived_after_last_read(self):
        user = self._reading_user()
        now = timezone.now()
        self._create_chat(
            provider_chat_id='c-1',
            last_message_at=now,
            last_read_at=now - timedelta(minutes=5),
        )
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertTrue(response.data['results'][0]['unread'])

    def test_unread_false_for_a_chat_with_no_messages_yet(self):
        user = self._reading_user()
        self._create_chat(provider_chat_id='c-1')
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertFalse(response.data['results'][0]['unread'])

    def test_pagination_respects_page_size(self):
        user = self._reading_user()
        for i in range(25):
            self._create_chat(provider_chat_id=f'c-{i}', last_message_at=timezone.now())
        response = self.client.get(self.URL, **self._auth_header(user))
        self.assertEqual(len(response.data['results']), 20)
        self.assertEqual(response.data['count'], 25)
        self.assertIsNotNone(response.data['next'])


class ChatMessagesViewTests(ChatsApiTestCase):
    def setUp(self):
        super().setUp()
        self.chat = self._create_chat(provider_chat_id='c-1')

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
        self.chat = self._create_chat(provider_chat_id='c-1')

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


class ChatOfficeIsolationTests(ChatsApiTestCase):
    """Step 5 (Inbox <-> Office integration) — the 9 scenarios explicitly
    required: Superadmin/Global Admin see every Office's Inbox; Office
    Admin/Operator see only their own Office; a user with no Office
    membership gets none at all (not even a legacy `office=None` chat —
    see apps/chats/authorization.py's own docstring); and none of this
    leaks through the existing list/messages/read endpoints."""

    def setUp(self):
        super().setUp()
        self.office_b = Office.objects.create(name='Office B')
        self.chat_a = self._create_chat(provider_chat_id='chat-a', office=self.office)
        self.chat_b = self._create_chat(provider_chat_id='chat-b', office=self.office_b)

    def _superadmin(self, username='superadmin'):
        return User.objects.create_superuser(username, f'{username}@example.com', 'pw')

    def _visible_ids(self, user):
        response = self.client.get('/api/chats/', **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        return {row['id'] for row in response.data['results']}

    # 1 & 2. SUPERADMIN can access Office A's and Office B's Inbox.
    def test_superadmin_sees_both_offices_on_list(self):
        user = self._superadmin()
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk, self.chat_b.pk})

    def test_superadmin_can_open_office_a_chat_detail(self):
        user = self._superadmin()
        response = self.client.get(f'/api/chats/{self.chat_a.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 200)

    def test_superadmin_can_open_office_b_chat_detail(self):
        user = self._superadmin()
        response = self.client.get(f'/api/chats/{self.chat_b.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 200)

    # 3. GLOBAL_ADMIN can access both Office A's and Office B's Inbox.
    def test_global_admin_sees_both_offices_on_list(self):
        user = self._reading_user('globaladmin', role=ROLE_GLOBAL_ADMIN)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk, self.chat_b.pk})

    def test_global_admin_can_open_office_b_chat_detail(self):
        user = self._reading_user('globaladmin', role=ROLE_GLOBAL_ADMIN)
        response = self.client.get(f'/api/chats/{self.chat_b.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 200)

    # 4 & 5. OFFICE_ADMIN/OPERATOR of Office A only see Office A.
    def test_office_admin_a_sees_only_office_a_on_list(self):
        user = self._reading_user('officeadmin_a', office=self.office, role=ROLE_OFFICE_ADMIN)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk})

    def test_operator_a_sees_only_office_a_on_list(self):
        user = self._reading_user('operator_a', office=self.office, role=ROLE_OPERATOR)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk})

    # 6 & 7. OFFICE_ADMIN/OPERATOR of Office A cannot reach Office B.
    def test_office_admin_a_cannot_open_office_b_chat_detail(self):
        user = self._reading_user('officeadmin_a', office=self.office, role=ROLE_OFFICE_ADMIN)
        response = self.client.get(f'/api/chats/{self.chat_b.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_operator_a_cannot_open_office_b_chat_detail(self):
        user = self._reading_user('operator_a', office=self.office, role=ROLE_OPERATOR)
        response = self.client.get(f'/api/chats/{self.chat_b.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_a_cannot_mark_office_b_chat_read(self):
        # Mark-as-read is a mutation on an existing endpoint — the same
        # boundary must hold there too, not just on reads.
        user = self._reading_user('officeadmin_a', office=self.office, role=ROLE_OFFICE_ADMIN)
        response = self.client.post(f'/api/chats/{self.chat_b.pk}/read/', **self._auth_header(user))
        self.assertEqual(response.status_code, 403)
        self.chat_b.refresh_from_db()
        self.assertIsNone(self.chat_b.last_read_at)

    # 8. A user with no Office membership gets no Office Inbox access.
    def test_user_without_any_office_sees_no_chats_on_list(self):
        user = self._reading_user('nooffice', office=None)
        self.assertEqual(self._visible_ids(user), set())

    def test_user_without_any_office_cannot_open_any_chat_detail(self):
        user = self._reading_user('nooffice', office=None)
        response = self.client.get(f'/api/chats/{self.chat_a.pk}/messages/', **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    # 9. No cross-office leakage through the existing list/detail endpoints.
    def test_office_b_chat_never_appears_in_office_a_admins_list(self):
        user = self._reading_user('officeadmin_a', office=self.office, role=ROLE_OFFICE_ADMIN)
        self.assertNotIn(self.chat_b.pk, self._visible_ids(user))


class ChatRoleWithoutReadingScopeTests(ChatOfficeIsolationTests):
    """Step 8 (Role x Scope alignment) — proves Inbox access now comes
    from `HasOfficeAccess` (organizational role), not the `reading` Group/
    scope: every user here explicitly has NO `reading` Group at all, only
    an `OfficeMembership` (or `is_superuser`/Global Admin role). Reuses
    `ChatOfficeIsolationTests`'s office_a/office_b/chat_a/chat_b fixtures.
    """

    def _role_only_user(self, username, office=_DEFAULT_OFFICE, role=ROLE_OPERATOR):
        user = User.objects.create_user(username, password='pw')
        # Deliberately NOT adding the 'reading' Group — this is the whole
        # point of this test class.
        if role == ROLE_GLOBAL_ADMIN:
            OfficeMembership.objects.create(
                user=user, office=None, role=_seeded_role(ROLE_GLOBAL_ADMIN), requires_office=False
            )
        else:
            actual_office = self.office if office is _DEFAULT_OFFICE else office
            role_obj = _seeded_role(role)
            OfficeMembership.objects.create(
                user=user, office=actual_office, role=role_obj, requires_office=not role_obj.grants_global_access
            )
        return user

    def test_office_admin_without_reading_scope_can_list_own_office_chats(self):
        user = self._role_only_user('roleonly_admin_a', office=self.office, role=ROLE_OFFICE_ADMIN)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk})

    def test_operator_without_reading_scope_can_list_own_office_chats(self):
        user = self._role_only_user('roleonly_operator_a', office=self.office, role=ROLE_OPERATOR)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk})

    def test_operator_without_reading_scope_cannot_see_office_b(self):
        user = self._role_only_user('roleonly_operator_a2', office=self.office, role=ROLE_OPERATOR)
        self.assertNotIn(self.chat_b.pk, self._visible_ids(user))

    def test_global_admin_without_reading_scope_sees_every_office(self):
        user = self._role_only_user('roleonly_gadmin', role=ROLE_GLOBAL_ADMIN)
        self.assertEqual(self._visible_ids(user), {self.chat_a.pk, self.chat_b.pk})

    def test_superuser_without_any_group_sees_every_office(self):
        superuser = User.objects.create_superuser('roleonly_super', 'super@example.com', 'pw')
        self.assertEqual(superuser.groups.count(), 0)
        self.assertEqual(self._visible_ids(superuser), {self.chat_a.pk, self.chat_b.pk})

    def test_authenticated_user_with_neither_role_nor_reading_scope_is_still_forbidden(self):
        # HasOfficeAccess must not become a blanket "any authenticated
        # user" bypass — someone with no OfficeMembership at all and no
        # 'reading' Group must still be denied.
        user = User.objects.create_user('nothing_at_all', password='pw')
        response = self.client.get('/api/chats/', **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_without_reading_scope_can_mark_own_office_chat_read(self):
        user = self._role_only_user('roleonly_admin_a2', office=self.office, role=ROLE_OFFICE_ADMIN)
        response = self.client.post(f'/api/chats/{self.chat_a.pk}/read/', **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
