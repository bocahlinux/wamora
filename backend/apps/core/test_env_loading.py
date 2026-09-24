import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config.env import load_env_file


class LoadEnvFileTests(SimpleTestCase):
    """docs/generated/PHASE-7-ENV-LOADING-FIX-REPORT.md: local-development
    .env auto-loading. Tests the exact function config/settings.py calls,
    not a re-implementation of it."""

    def _write_env_file(self, content: str) -> Path:
        tmp_dir = tempfile.mkdtemp()
        path = Path(tmp_dir) / '.env'
        path.write_text(content, encoding='utf-8')
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_loads_values_from_a_present_file(self):
        path = self._write_env_file('SOME_TEST_VAR=from-dotenv\n')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SOME_TEST_VAR', None)
            load_env_file(path)
            self.assertEqual(os.environ.get('SOME_TEST_VAR'), 'from-dotenv')

    def test_already_exported_environment_variable_takes_precedence(self):
        path = self._write_env_file('SOME_TEST_VAR=from-dotenv\n')
        with mock.patch.dict(os.environ, {'SOME_TEST_VAR': 'from-real-shell'}, clear=False):
            load_env_file(path)
            self.assertEqual(os.environ.get('SOME_TEST_VAR'), 'from-real-shell')

    def test_missing_file_is_a_silent_no_op(self):
        """Production-safety requirement: Docker/production never has
        backend/.env present (backend/.dockerignore excludes it from the
        image) — this must never raise or otherwise depend on the file
        existing."""
        missing_path = Path(tempfile.mkdtemp()) / 'does-not-exist' / '.env'
        before = dict(os.environ)
        try:
            load_env_file(missing_path)  # must not raise
        except Exception as exc:  # pragma: no cover - failure path only
            self.fail(f'load_env_file raised for a missing file: {exc!r}')
        self.assertEqual(dict(os.environ), before, 'a missing .env must never mutate os.environ')

    def test_blank_and_comment_lines_are_tolerated(self):
        path = self._write_env_file('\n# a comment\nSOME_TEST_VAR=value\n')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SOME_TEST_VAR', None)
            load_env_file(path)
            self.assertEqual(os.environ.get('SOME_TEST_VAR'), 'value')
