from django.contrib.auth.models import User
from django.test import TestCase

from apps.blast.models import BlastApiKey


class BlastApiKeyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('creator', password='pw')

    def test_create_with_raw_key_returns_a_usable_key_and_never_stores_it_raw(self):
        key, raw_key = BlastApiKey.create_with_raw_key(name='Tax system', created_by=self.user)
        self.assertTrue(raw_key)
        self.assertNotEqual(key.key_hash, raw_key)
        self.assertEqual(key.key_prefix, raw_key[:8])
        # The raw key is never persisted anywhere retrievable from the row.
        key.refresh_from_db()
        self.assertNotIn(raw_key, key.key_hash)

    def test_authenticate_succeeds_with_the_correct_raw_key(self):
        key, raw_key = BlastApiKey.create_with_raw_key(name='Tax system', created_by=self.user)
        found = BlastApiKey.authenticate(raw_key)
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, key.pk)

    def test_authenticate_fails_with_a_wrong_key(self):
        BlastApiKey.create_with_raw_key(name='Tax system', created_by=self.user)
        self.assertIsNone(BlastApiKey.authenticate('not-the-real-key'))

    def test_authenticate_fails_for_a_revoked_key(self):
        key, raw_key = BlastApiKey.create_with_raw_key(name='Tax system', created_by=self.user)
        BlastApiKey.objects.filter(pk=key.pk).update(is_active=False)
        self.assertIsNone(BlastApiKey.authenticate(raw_key))

    def test_two_keys_never_collide(self):
        _key1, raw1 = BlastApiKey.create_with_raw_key(name='A', created_by=self.user)
        _key2, raw2 = BlastApiKey.create_with_raw_key(name='B', created_by=self.user)
        self.assertNotEqual(raw1, raw2)
