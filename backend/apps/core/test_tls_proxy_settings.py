"""Phase 14 Blocker B3 (TLS/reverse proxy) — config/settings.py's
`DJANGO_BEHIND_TLS_PROXY`-gated block.

Django settings are loaded once per process (django.setup() cannot be
re-run with a different environment inside this same test process
without corrupting the app registry other tests rely on), so this test
runs a fresh subprocess per case instead — the only reliable way to
observe how config/settings.py itself behaves under a different
DJANGO_BEHIND_TLS_PROXY value, without disturbing this test process's
own already-configured Django.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BACKEND_DIR = Path(__file__).resolve().parents[2]

SETTING_NAMES = (
    'SECURE_PROXY_SSL_HEADER',
    'SECURE_SSL_REDIRECT',
    'SECURE_HSTS_SECONDS',
    'SECURE_HSTS_INCLUDE_SUBDOMAINS',
)

_PROBE = (
    'import django, json; django.setup(); from django.conf import settings; '
    'print(json.dumps({n: getattr(settings, n, "__UNSET__") for n in '
    + repr(list(SETTING_NAMES))
    + '}))'
)


def _read_settings(behind_tls_proxy):
    env = dict(os.environ)
    env['DJANGO_SETTINGS_MODULE'] = 'config.settings_test'
    if behind_tls_proxy is None:
        env.pop('DJANGO_BEHIND_TLS_PROXY', None)
    else:
        env['DJANGO_BEHIND_TLS_PROXY'] = behind_tls_proxy

    result = subprocess.run(
        [sys.executable, '-c', _PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_DIR),
        timeout=30,
    )
    assert result.returncode == 0, f'settings probe subprocess failed: {result.stderr}'
    return json.loads(result.stdout.strip())


class DjangoBehindTlsProxySettingTests(SimpleTestCase):
    def test_defaults_to_off_when_unset(self):
        # Django's own global_settings.py already defaults every one of
        # these to its safe/off value (None / False / 0 / False) — our
        # settings.py block simply never runs, it doesn't need to
        # explicitly set an "off" value itself.
        values = _read_settings(behind_tls_proxy=None)
        self.assertIsNone(values['SECURE_PROXY_SSL_HEADER'])
        self.assertEqual(values['SECURE_SSL_REDIRECT'], False)
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 0)
        self.assertEqual(values['SECURE_HSTS_INCLUDE_SUBDOMAINS'], False)

    def test_defaults_to_off_when_explicitly_false(self):
        values = _read_settings(behind_tls_proxy='False')
        self.assertEqual(values['SECURE_SSL_REDIRECT'], False)

    def test_enables_the_full_bundle_when_true(self):
        values = _read_settings(behind_tls_proxy='True')
        self.assertEqual(values['SECURE_PROXY_SSL_HEADER'], ['HTTP_X_FORWARDED_PROTO', 'https'])
        self.assertEqual(values['SECURE_SSL_REDIRECT'], True)
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 31536000)
        self.assertEqual(values['SECURE_HSTS_INCLUDE_SUBDOMAINS'], True)
