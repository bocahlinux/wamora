from django.contrib.auth.models import User
from django.test import TestCase

from apps.blast.models import BlastTemplate
from apps.blast.serializers import BlastCampaignCreateSerializer
from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession


class _Request:
    """Minimal stand-in for DRF's request wrapper — the serializer only
    ever reads `.user` off `context['request']`."""

    def __init__(self, user):
        self.user = user


def _global_user(username='super'):
    return User.objects.create_superuser(username, f'{username}@example.com', 'pw')


class BlastCampaignCreateSerializerFreeformTests(TestCase):
    """The original, freeform (no template) path — must keep working
    byte-for-byte (additive change, CLAUDE.md rule 8)."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.office = Office.objects.create(name='Office A')
        self.user = _global_user()

    def _data(self, **overrides):
        data = {
            'session': self.session.name,
            'office': self.office.pk,
            'name': 'Campaign',
            'message_template': 'Halo semua',
            'recipients': ['+6280000000001', '+6280000000002'],
        }
        data.update(overrides)
        return data

    def test_bare_string_recipients_are_accepted(self):
        serializer = BlastCampaignCreateSerializer(data=self._data(), context={'request': _Request(self.user)})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        campaign = serializer.save()
        self.assertEqual(campaign.message_template, 'Halo semua')
        self.assertEqual(set(campaign.recipients.values_list('destination', flat=True)), {'+6280000000001', '+6280000000002'})
        self.assertTrue(all(r.variables == {} for r in campaign.recipients.all()))

    def test_blank_message_template_without_a_template_is_rejected(self):
        serializer = BlastCampaignCreateSerializer(
            data=self._data(message_template=''), context={'request': _Request(self.user)},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('message_template', serializer.errors)

    def test_duplicate_recipients_are_deduplicated(self):
        serializer = BlastCampaignCreateSerializer(
            data=self._data(recipients=['+6280000000001', '+6280000000001']),
            context={'request': _Request(self.user)},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        campaign = serializer.save()
        self.assertEqual(campaign.recipients.count(), 1)


class BlastCampaignCreateSerializerTemplatePathTests(TestCase):
    """Discussed requirement — per-recipient variables, all-or-nothing
    validation: ANY recipient row with missing/mismatched variables
    rejects the WHOLE upload."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.office = Office.objects.create(name='Office A')
        self.user = _global_user()
        self.template = BlastTemplate.objects.create(
            key='pajak-jatuh-tempo', name='Pajak Jatuh Tempo',
            content='Yth, {{nama_wp}} Nopol {{nopol}} jatuh tempo {{jatuh_tempo}}',
            created_by=self.user,
        )

    def _data(self, recipients, **overrides):
        data = {
            'session': self.session.name,
            'office': self.office.pk,
            'name': 'Tax reminder',
            'template': self.template.pk,
            'recipients': recipients,
        }
        data.update(overrides)
        return data

    def test_matching_variables_on_every_row_succeeds(self):
        recipients = [
            {'destination': '+6280000000001', 'variables': {'nama_wp': 'Anto', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025'}},
            {'destination': '+6280000000002', 'variables': {'nama_wp': 'Budi', 'nopol': 'KH5678BB', 'jatuh_tempo': '20-05-2025'}},
        ]
        serializer = BlastCampaignCreateSerializer(data=self._data(recipients), context={'request': _Request(self.user)})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        campaign = serializer.save()
        # message_template is the server-side SNAPSHOT of the template's
        # content, never the client's own (unsupplied) value.
        self.assertEqual(campaign.message_template, self.template.content)
        self.assertEqual(campaign.template_id, self.template.pk)
        recipient = campaign.recipients.get(destination='+6280000000001')
        self.assertEqual(recipient.variables, {'nama_wp': 'Anto', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025'})

    def test_one_row_missing_a_variable_rejects_the_whole_request(self):
        recipients = [
            {'destination': '+6280000000001', 'variables': {'nama_wp': 'Anto', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025'}},
            # Missing jatuh_tempo entirely.
            {'destination': '+6280000000002', 'variables': {'nama_wp': 'Budi', 'nopol': 'KH5678BB'}},
        ]
        serializer = BlastCampaignCreateSerializer(data=self._data(recipients), context={'request': _Request(self.user)})
        self.assertFalse(serializer.is_valid())
        self.assertIn('recipients', serializer.errors)
        details = serializer.errors['details']
        self.assertEqual(len(details), 1)
        # `serializer.errors` (accessed directly, not through
        # apps.blast.views._serializer_error_response's normalization)
        # exposes DRF's raw ErrorDetail-wrapped values — every leaf,
        # including the int `index` `validate()` set, comes back as a
        # str-subclass ErrorDetail. Compared as str here; the view layer
        # normalizes it back to a real int before it ever reaches the
        # frontend (see views.py's own comment on this exact quirk).
        self.assertEqual(str(details[0]['index']), '1')
        self.assertEqual(details[0]['destination'], '+6280000000002')
        self.assertIn('jatuh_tempo', details[0]['missing'])
        from apps.blast.models import BlastCampaign
        self.assertEqual(BlastCampaign.objects.count(), 0)  # nothing created — all-or-nothing

    def test_one_row_with_an_extra_unexpected_variable_rejects_the_whole_request(self):
        recipients = [
            {
                'destination': '+6280000000001',
                'variables': {
                    'nama_wp': 'Anto', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025', 'extra_field': 'oops',
                },
            },
        ]
        serializer = BlastCampaignCreateSerializer(data=self._data(recipients), context={'request': _Request(self.user)})
        self.assertFalse(serializer.is_valid())
        details = serializer.errors['details']
        self.assertIn('extra_field', details[0]['extra'])

    def test_blank_variable_value_counts_as_missing(self):
        recipients = [
            {'destination': '+6280000000001', 'variables': {'nama_wp': '', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025'}},
        ]
        serializer = BlastCampaignCreateSerializer(data=self._data(recipients), context={'request': _Request(self.user)})
        self.assertFalse(serializer.is_valid())
        self.assertIn('nama_wp', serializer.errors['details'][0]['missing'])

    def test_bare_string_recipient_with_a_template_is_rejected_as_missing_every_variable(self):
        recipients = ['+6280000000001']
        serializer = BlastCampaignCreateSerializer(data=self._data(recipients), context={'request': _Request(self.user)})
        self.assertFalse(serializer.is_valid())
        missing = set(serializer.errors['details'][0]['missing'])
        self.assertEqual(missing, {'nama_wp', 'nopol', 'jatuh_tempo'})

    def test_client_supplied_message_template_is_ignored_when_template_is_given(self):
        recipients = [
            {'destination': '+6280000000001', 'variables': {'nama_wp': 'Anto', 'nopol': 'KH1234AA', 'jatuh_tempo': '14-05-2025'}},
        ]
        serializer = BlastCampaignCreateSerializer(
            data=self._data(recipients, message_template='client tried to override this'),
            context={'request': _Request(self.user)},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        campaign = serializer.save()
        self.assertEqual(campaign.message_template, self.template.content)
