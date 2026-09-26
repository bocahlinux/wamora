"""Phase 13 (Failure/security testing) Track A, scope item 4 — secrets
absent from logs, as a permanent automated check rather than a one-off
manual grep.

`docs/generated/PHASE-13-FAILURE-SECURITY-TESTING-SCOPING-AUDIT-REPORT.md`
scope item 4: "no evidence found anywhere that this has ever been
checked, live or statically." The Blast and Phase 12 audits each did an
ad hoc grep by hand once; this turns that into a test that runs on every
`manage.py test`.

Method: walk every non-test, non-migration `.py` file under `backend/apps`
and `backend/config`, parse it with the real `ast` module (not a
line-by-line grep — a multi-line `logger.info(...)` call is captured as
one statement, not accidentally split), find every `logger.<level>(...)`
/ `print(...)` call site, and assert none of this project's known
secret-bearing settings names is referenced anywhere inside that call's
source text (arguments, f-strings, `.format()` placeholders — all of it,
since `ast.get_source_segment` returns the call's exact original text).

`SECRET_SETTING_NAMES` below is deliberately the same vocabulary named in
`docs/CLAUDE.md`/the task instructions: `WAHA_API_KEY`, the Django
`SECRET_KEY` (sourced from the `DJANGO_SECRET_KEY` env var — application
code reads `settings.SECRET_KEY`, never `settings.DJANGO_SECRET_KEY`, so
both spellings are checked), `INTERNAL_SERVICE_KEY`,
`OFFICE_DISPATCH_SERVICE_KEY`, `WAHA_WEBHOOK_HMAC_SECRET`, and
`JWT_PRIVATE_KEY`. Deliberately NOT included: `JWT_PUBLIC_KEY` (public by
design — see `apps/authn/jwt_utils.py`'s own docstring) and `JWT_KID` (a
key identifier, not key material).

Per the scoping audit's own caution: if this test ever finds a real
violation, do not paste the matched secret value anywhere — the
assertion message below only ever names the file/line/setting-name, never
any file content, so a real failure's own output stays safe to share.
"""

import ast
import os
import re

from django.conf import settings
from django.test import SimpleTestCase

SCAN_ROOTS = [
    os.path.join(str(settings.BASE_DIR), 'apps'),
    os.path.join(str(settings.BASE_DIR), 'config'),
]

# Directory names to never descend into: migrations are generated,
# tests/__pycache__/venv are not this project's application source.
EXCLUDED_DIR_NAMES = {'migrations', '__pycache__', 'tests', 'venv', 'node_modules'}

LOG_CALL_ATTRS = {'debug', 'info', 'warning', 'error', 'critical', 'exception', 'log'}

SECRET_SETTING_NAMES = [
    'SECRET_KEY',
    'DJANGO_SECRET_KEY',
    'WAHA_API_KEY',
    'INTERNAL_SERVICE_KEY',
    'OFFICE_DISPATCH_SERVICE_KEY',
    'WAHA_WEBHOOK_HMAC_SECRET',
    'JWT_PRIVATE_KEY',
]


def _iter_python_source_files():
    for root_dir in SCAN_ROOTS:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
            for filename in filenames:
                if not filename.endswith('.py'):
                    continue
                # Mirrors this project's own two test-file conventions
                # (apps/<app>/tests/test_*.py package style, and
                # apps/<app>/test_*.py / tests.py root-file style) —
                # already covered by the EXCLUDED_DIR_NAMES 'tests' entry
                # for the former; this covers the latter.
                if filename.startswith('test_') or filename.endswith('_test.py') or filename == 'tests.py':
                    continue
                yield os.path.join(dirpath, filename)


def _is_log_or_print_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name) and node.func.id == 'print':
        return True
    if isinstance(node.func, ast.Attribute) and node.func.attr in LOG_CALL_ATTRS:
        return True
    return False


def find_secret_logging_violations():
    """Returns a list of human-readable 'path:line references NAME'
    strings — empty if clean. Factored out of the test method so it can
    also be run standalone (`python -c "from apps.core.test_secrets_not_in_logs
    import find_secret_logging_violations as f; print(f())"`) without
    the Django test runner, e.g. for a quick manual re-check."""
    violations = []
    for path in _iter_python_source_files():
        with open(path, encoding='utf-8') as fh:
            source = fh.read()
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            # Not this check's job to enforce syntactic validity elsewhere.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_log_or_print_call(node):
                continue
            segment = ast.get_source_segment(source, node) or ''
            for name in SECRET_SETTING_NAMES:
                if re.search(rf'\b{re.escape(name)}\b', segment):
                    lineno = getattr(node, 'lineno', '?')
                    violations.append(f'{os.path.relpath(path, str(settings.BASE_DIR))}:{lineno} references {name}')
    return violations


class SecretsNotInLogsTests(SimpleTestCase):
    def test_scan_finds_at_least_one_real_logging_call_site(self):
        # Sanity check on the scanner itself, not the codebase: if this
        # ever returns 0, the AST walk/exclusion rules are almost
        # certainly broken (this project's views/services/tasks log
        # plenty), and the "no violations" result above would be
        # meaningless.
        total_calls = 0
        for path in _iter_python_source_files():
            with open(path, encoding='utf-8') as fh:
                source = fh.read()
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:
                continue
            total_calls += sum(
                1 for node in ast.walk(tree) if isinstance(node, ast.Call) and _is_log_or_print_call(node)
            )
        self.assertGreater(total_calls, 0, 'scanner found zero logger/print call sites — check EXCLUDED_DIR_NAMES/glob logic')

    def test_no_secret_setting_is_logged_or_printed(self):
        violations = find_secret_logging_violations()
        self.assertEqual(
            violations,
            [],
            'Secret-bearing setting(s) referenced inside a logging/print call — never log secret material '
            '(docs/06-SECURITY.md):\n' + '\n'.join(violations),
        )
