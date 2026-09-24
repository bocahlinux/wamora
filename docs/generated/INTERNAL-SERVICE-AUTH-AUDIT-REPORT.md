# Internal Service Auth — Why Django Returns 403 (Read-Only Audit)

Follow-up to
[`INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md`](INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md).
Your live BFF log now shows the request genuinely reaches Django and is
rejected: `status=403 code=permission_denied`, for both
`/internal/outbound-operations/` and `/internal/reconciliation/trigger/`.
**Read-only audit** — no source code, `.env`, database, WAHA state, or
BFF behavior was changed; no WhatsApp message was sent; no internal
endpoint was invoked live; no diagnostic logging was added (would have
required your prior approval, which wasn't sought since it wasn't
needed to reach a conclusion).

## Direct answers

**Header BFF sends**: `X-Internal-Service-Key` — confirmed both from
`bff/src/djangoClient.ts:57-60` (`'X-Internal-Service-Key':
options.serviceKey`) and from your own live log line itself
(`X-Internal-Service-Key attached, length=64`).

**Header Django expects**: `apps/core/internal_auth.py:15`,
`HEADER_NAME = 'HTTP_X_INTERNAL_SERVICE_KEY'`. This is the exact,
correct WSGI-normalized form of the header BFF sends (WSGI/Django always
maps an inbound HTTP header `X-Internal-Service-Key` to
`request.META['HTTP_X_INTERNAL_SERVICE_KEY']` — uppercase, hyphens to
underscores, `HTTP_` prefix). **These match exactly — header-name
mismatch is ruled out** by direct code inspection, not inference.

**Where Django gets the expected key from**: `config/settings.py:305`,
`INTERNAL_SERVICE_KEY = os.environ.get('INTERNAL_SERVICE_KEY', '')` —
read once, at Django process startup, from `os.environ`.
`os.environ` itself is populated by `config/env.py::load_env_file()`,
called unconditionally at the top of `settings.py` for every
`manage.py` invocation (including `runserver`), which loads
`backend/.env` via **`load_dotenv(path, override=False)`**
(`config/env.py:29`) — explicitly documented in that file's own
docstring: *"without overriding a variable that's already set in the
real environment... an operator who has explicitly exported/injected a
value always wins over the file."*

**This `override=False` is the single most important fact in this
audit.** It means: if `INTERNAL_SERVICE_KEY` was already present in the
`os.environ` of the specific shell/terminal that launched
`python manage.py runserver` — for any reason, at any earlier point —
**Django will silently keep using that shell-inherited value and ignore
whatever `backend/.env` currently contains**, even across a full kill
and restart of the Python process, as long as that restart happens from
the same shell session (a new child process still inherits its parent
shell's exported environment).

**Does the live BFF and Django use the same secret?** **Not provably
confirmed — and this is exactly the gap `override=False` opens up.**
What *is* confirmed, read-only, this task:
- `bff/.env` and `backend/.env`'s current `INTERNAL_SERVICE_KEY` file
  contents are byte-identical (confirmed in the prior audit, re-stated
  here as still relevant, not re-verified again this task since nothing
  indicates either file changed).
- **No persistent Windows environment variable** named
  `INTERNAL_SERVICE_KEY` exists at User, Machine, or (this session's)
  Process scope (`[Environment]::GetEnvironmentVariable(...)`, all three
  scopes checked, all empty) — rules out a system-wide/registry-level
  stale override.
- **No workspace/IDE config** (`.vscode/`, no `.json`/`.ps1`/`.cmd`/`.bat`
  file anywhere in the repo) references `INTERNAL_SERVICE_KEY` outside
  `.env` — rules out an IDE-injected environment override.
- **What remains unruled-out, and unreachable from outside**: a
  **session-scoped** shell export (e.g. `$env:INTERNAL_SERVICE_KEY =
  "..."` typed directly into the specific PowerShell/terminal window
  that is currently running `python manage.py runserver`, at any earlier
  point in that window's lifetime — including possibly during this
  project's own earlier debugging steps, if a value was ever
  hand-exported there instead of only edited into `.env`). This is
  invisible to any other process (including every check this audit ran),
  because Windows environment variables set only inside one running
  shell are not visible to sibling processes, the registry, or a
  freshly-spawned shell like the ones this audit used.

**If they're genuinely the same, why 403 anyway?** No evidence found
for this branch — every mechanical possibility checked (header name,
comparison logic, encoding) matches correctly (below). Given
`override=False` provides a complete, well-documented, and unverifiable-
from-outside explanation for a *difference*, this audit's conclusion is
that the values most likely **do differ live**, not that they match and
something else is wrong.

## What was checked, and ruled out

1. **`HasInternalServiceKey.has_permission()` logic**
   (`apps/core/internal_auth.py:23-30`):
   ```python
   def has_permission(self, request, view):
       configured = settings.INTERNAL_SERVICE_KEY
       if not configured:
           return False
       provided = request.META.get(HEADER_NAME, '')
       if not provided:
           return False
       return hmac.compare_digest(provided, configured)
   ```
   Straightforward: both `provided` and `configured` are plain Python
   `str` (WSGI headers are always `str`; `os.environ.get()` returns
   `str`) — no `str`/`bytes` type-mismatch risk for `hmac.compare_digest`
   (which raises `TypeError` on mixed types — that would produce a `500`,
   not a `403`, and no such error is implied by your log). No other
   branch could produce this specific `403`/`permission_denied` besides
   the final `compare_digest` returning `False`.

2. **Confirms the 403 genuinely comes from `HasInternalServiceKey`, not
   another layer** (your point 6 — request-ID-based confirmation): rather
   than looking up the specific UUIDs (Django logs to console only, no
   file — nothing persists a rejected request by ID to query
   retroactively), this is confirmed **structurally, by code**:
   - `code: 'permission_denied'` in the response body is DRF's own
     **default** `rest_framework.exceptions.PermissionDenied.default_code`
     — automatically raised by DRF's `APIView.check_permissions()`
     whenever any permission class's `has_permission()` returns `False`.
     `ReconciliationTriggerView`/`OutboundOperationRegisterView` both
     declare `permission_classes = [HasInternalServiceKey]` — the only
     permission class in the chain.
   - `authentication_classes = []` on both views rules out a rejection
     from Django/DRF's authentication layer (there is none configured).
   - `request_id` in the response body is set by
     `apps.core.middleware.RequestIDMiddleware` (`config/settings.py:87`),
     confirming the request passed through this project's own full
     middleware stack and reached DRF's view-dispatch/permission-check
     stage — not a generic web-server or proxy-level 403 (there is no
     reverse proxy in this dev topology — `manage.py runserver` is hit
     directly).
   - `CsrfViewMiddleware` is in the stack but does not apply here: DRF's
     `APIView.as_view()` marks its dispatch `csrf_exempt` by design, and
     even if it didn't, a CSRF rejection produces Django's own native
     403 page shape, not this project's custom `{error: {code,
     message, request_id}}` envelope.
   - **Conclusion: this `403` is, with certainty, `HasInternalServiceKey.has_permission()`
     returning `False` via a failed `hmac.compare_digest`** — not a
     header-name mismatch, not a different permission/auth layer, not a
     proxy.

3. **`settings_test.py` misconfiguration** — ruled out: it only
   overrides `DATABASES` (`from .settings import *` then a SQLite
   override) and is never used to run the live dev server (`manage.py
   runserver` always uses the default `config.settings`, never
   `config.settings_test` — that module is invoked explicitly and only
   for `manage.py test`, per its own docstring).

4. **Whitespace/newline in the current `.env` files**: `bff/.env`'s
   `DJANGO_INTERNAL_BASE_URL` line was checked with `cat -A` in the prior
   audit and has a plain LF ending, no stray `\r`. The
   `INTERNAL_SERVICE_KEY` lines were not run through `cat -A` (that would
   print the literal secret to this transcript) — but the byte-for-byte
   equality check already performed (prior audit) inherently captures
   any such artifact identically on both sides, so it cannot be the
   source of a *difference between the two files*. It also does not
   explain why the *live process* would differ from *either* file, which
   is a `load_dotenv(override=False)` question, not a file-encoding one.

5. **Variable name mismatch** — ruled out: both `bff/.env` and
   `backend/.env` use the exact literal name `INTERNAL_SERVICE_KEY`
   (confirmed via names-only `grep` in the prior audit); `settings.py`
   reads that exact name; `config.ts` reads that exact name via
   `process.env.INTERNAL_SERVICE_KEY`.

6. **Middleware/proxy stripping or altering the header** — ruled out:
   full `MIDDLEWARE` list reviewed (`config/settings.py:79-94`) — none of
   `SecurityMiddleware`, `CorsMiddleware`, `RequestIDMiddleware`,
   `SessionMiddleware`, `CommonMiddleware`, `CsrfViewMiddleware`,
   `AuthenticationMiddleware`, `MessageMiddleware`, or
   `XFrameOptionsMiddleware` touches custom `HTTP_X_*` headers; there is
   no reverse proxy in this dev topology (BFF calls `manage.py runserver`
   directly by IP:port).

## Root cause

**CONFIRMED**: the mechanism that makes a live-process/`.env`-file
divergence possible is `config/env.py::load_env_file()`'s
`load_dotenv(path, override=False)` — by design, an already-set
`os.environ` value always wins over the current `.env` file content, for
the entire lifetime of the process (and any process later started from
the same shell).

**LIKELY**: the actual live `python manage.py runserver` process's
`INTERNAL_SERVICE_KEY` does not match the current `backend/.env` file,
because that terminal session has (or had, at some point before its most
recent restart) `INTERNAL_SERVICE_KEY` already present in its own shell
environment, silently shadowing every subsequent edit to the file for as
long as that shell session persists.

**NOT PROVEN**: the actual live value itself — this audit has no way to
read another running process's environment block without either (a) a
live diagnostic call you haven't approved, or (b) you inspecting that
exact terminal session yourself.

**Symmetric, unproven possibility worth naming**: the same
`override=False`-style precedence is standard behavior for `.env` file
loaders in general, including (by the same convention, though not
independently re-verified against Node's own documentation in this
task) Node's `--env-file-if-exists` flag the BFF uses
(`bff/package.json`'s `dev` script). So the divergence could
symmetrically be on the **BFF's** side instead of (or in addition to)
Django's — the observable symptom (`403`) would look identical either
way, since it only takes one side using a stale value for
`hmac.compare_digest` to fail.

## How to confirm, without any code/endpoint change (for you to run)

The one check this audit cannot perform itself: **in the exact terminal
window currently running `python manage.py runserver`**, without
restarting anything, run:
```
echo $env:INTERNAL_SERVICE_KEY          (PowerShell)
```
If that prints a non-empty value, **that is the smoking gun** — it means
this specific shell has its own exported value, independent of
`backend/.env`, and `override=False` means Django is using *that*, not
your file. If it prints nothing, the shell itself has no override, and
the divergence (if any) would have to be explained differently (worth a
follow-up audit at that point). The same check, `echo $env:INTERNAL_SERVICE_KEY`,
is also worth running in the exact terminal running the BFF's `npm run
dev`, for the symmetric reason above.

If either terminal shows a stray export, the fix (not performed by this
task) would simply be: fully close that terminal window (not just
Ctrl+C the process — an exported shell variable survives Ctrl+C, since
the shell itself keeps running) and start a brand-new terminal before
re-running `manage.py runserver` / `npm run dev`, so the fresh shell has
nothing to shadow `.env` with.

---

No source code, `.env`, database, or WAHA session was changed. No
WhatsApp message was sent. No internal endpoint was invoked live. No
diagnostic logging was added. Not proceeding to Phase 9 or any other
task — stopping here as instructed, awaiting your terminal-side check.
