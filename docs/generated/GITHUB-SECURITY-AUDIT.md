# GitHub Security Audit

Read-only audit. No file was modified, no credential was rotated, no
secret value is printed anywhere below. Where a secret-like value was
found, only its type/location/Git-tracking status is reported, never the
value itself.

**Foundational finding, checked first**: `git status` returns `fatal:
not a git repository (or any of the parent directories): .git` — **this
directory has no Git repository at all** (confirmed: no `.git/` anywhere
under the project root, including nested). This changes the shape of the
whole audit:

- Section 1 ("Git tracking audit") and Section 4 ("Git history audit"),
  as originally framed, don't apply literally — there is no `git
  ls-files`, no commit history, nothing currently "tracked" in the Git
  sense. **Nothing has ever been pushed anywhere; there is no history to
  leak from.**
- This audit instead answers the practically-equivalent question: *if
  `git init` + `git add -A` were run right now, using the existing
  `.gitignore`, what would end up staged?* — a full filesystem scan,
  cross-checked against `.gitignore`'s actual patterns, was performed for
  this purpose (Section 1 below).
- This is good news structurally (no historical-leak cleanup, no `git
  filter-repo`/history-rewrite question applies), but it also means nothing
  has forced a real "would this get committed" check until now — this is
  that check.

## Overall status

**SAFE AFTER REMEDIATION**

No hardcoded credential, API key, password, or token was found in any
file that would be committed. The blocking issue is not a leaked secret —
it's real third-party personal data (WhatsApp contact phone numbers) and
internal infrastructure identifiers embedded in documentation and
committed test fixtures, plus one `.gitignore` gap. All are fixable
without rotating anything.

## Critical findings

None.

## High findings

**H1 — Real third-party phone numbers and WhatsApp identifiers are
embedded in documentation and committed test fixtures.**

Real numbers/identifiers (`62800000000`, `62800000001`,
`000000000000000@lid`, and the associated session name `test_session` /
business handle `@test_business`) appear across **17+ files**,
including:
- `docs/12-WAHA-REFERENCE.md` (the canonical, most-referenced doc)
- Multiple files under `docs/generated/`
- **Committed test fixtures**: `backend/apps/webhooks/tests/fixtures.py`,
  `backend/apps/sync/tests/fixtures.py`, and several `test_*.py` files
  that import from them

These are real phone numbers belonging to real third parties (WhatsApp
contacts of the business this project monitors) and a real business
session identifier — not synthetic test data. Publishing them on a
public GitHub repository exposes personal data belonging to people who
never consented to appearing in a public software repository, and ties
that data to a specific identifiable business. This is a privacy
concern independent of whether any credential is involved, and
depending on jurisdiction may carry data-protection implications.

**Recommended remediation**: before publishing, replace every real
phone number / LID / session name in `docs/` and in test fixtures with
clearly-synthetic values (e.g. `62800000000@s.whatsapp.net`,
`000000000000000@lid`, `test_session`) — this project's own
`backend/apps/sync/tests/test_waha_client.py` already demonstrates the
right pattern (`'test-api-key'`, `waha.internal:3000`). The evidentiary
value of the real examples (documented in `docs/12-WAHA-REFERENCE.md`
and the Phase 3/4/5/6 `generated/` reports) can be preserved by keeping
the *shape*/format observations while anonymizing the literal values.

## Medium findings

**M1 — Real internal infrastructure IPs are documented across 6 files.**

`<TENCENT_WAHA_HOST>` (the Tencent WAHA host, a NetBird/CGNAT-range address,
`100.64.0.0/10`) and `<OFFICE_DB_HOST>` (the PostgreSQL host, RFC1918
private LAN range) appear in `docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md`,
`PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md`, `PHASE-6-ARCHITECTURE-DECISION.md`,
`PHASE-6-SPEC-RESOLUTION.md`, `PHASE-5-LIVE-VERIFICATION.md`, and
`PHASE-3-LIVE-VERIFICATION.md` — plus, expectedly, the two real `.env`
files (not committable, see Section 1).

Neither IP is publicly routable, so this is **not** a direct
"attacker can now reach your server" exposure — both only mean anything
to someone already on the NetBird mesh or the office LAN. This is why it
is Medium, not High/Critical. It is still real infrastructure
topology information (which host is WAHA, which is PostgreSQL, their
exact addresses) that a public repo doesn't need to carry. This task's
own instructions acknowledge this is a judgment call ("real
infrastructure IPs may be documented if intentionally part of the
project's architecture") — this document does not silently decide it
either way.

**Recommended remediation (your call, not decided here)**: either
accept these as documented, private-range, access-gated addresses (a
defensible choice, since they're not publicly reachable), or replace
them with placeholders (`<TENCENT_WAHA_HOST>`, `<OFFICE_DB_HOST>`) in
`docs/generated/` before publishing, consistent with how
`docs/00-MASTER-SPEC.md` and the other numbered `docs/` files already
avoid hardcoding real addresses.

**M2 — `.gitignore` only matches the literal filename `.env`, not
`.env.*` variants.**

Current patterns: `.env`, `*/.env`, `**/.env`, `!**/.env.example`. A
file named `backend/.env.local`, `backend/.env.production`, or similar
would **not** be excluded by any of these patterns — only an exact `.env`
filename is covered. No such file currently exists (confirmed by a
filesystem scan), so nothing is exposed *today*, but this is a real gap
that could bite the moment someone creates an environment-specific
`.env` variant. See Section 6 for the specific recommended addition.

## Low findings

**L1 — `backend/config/settings.py` line 19: `SECRET_KEY =
os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-only-placeholder')`.**

The fallback value is clearly labeled as an insecure placeholder (not a
real secret, and this exact string is a well-known Django scaffold
convention) — not a leaked credential. The concern is behavioral, not a
data exposure: if `DJANGO_SECRET_KEY` is ever left unset in a real
deployment, Django will **silently start up** using this
publicly-known placeholder instead of failing loudly. Recommended
remediation: raise `django.core.exceptions.ImproperlyConfigured` if
`DJANGO_SECRET_KEY` is unset and `DEBUG` is `False`, rather than falling
back silently — a behavior change, not a secret-removal, so listed as
Low/hygiene rather than a real finding of exposed material.

**L2 — Root-level `WAHA-Dashboard-Claude-Engineering-Pack-FINAL.zip`
(≈13KB, 18 files) is a duplicate of `docs/` content.**

Inspected via `unzip -l` (listing only, not extracted) — contains the
same specification `.md` files already present, unpacked, in `docs/`.
Not a secret-exposure risk (checked: same non-sensitive spec content),
but it's dead weight sitting at the repo root, uncovered by
`.gitignore`, that would be committed as a redundant binary blob.
Recommended: remove it (or add it to `.gitignore`) before publishing,
purely for repository hygiene, not security.

## Clean checks

- **No hardcoded real credentials found** in any file that would be
  committed — searched `backend/`, `bff/`, `frontend/`,
  `infrastructure/`, `docs/`, `scripts/`, `README.md` for WAHA API keys,
  HMAC secrets, DB passwords, Django `SECRET_KEY` values, JWT-looking
  tokens (`eyJ...`), private-key markers (`-----BEGIN`), cloud-provider
  key patterns (AWS `AKIA...`, GitHub `ghp_...`, Slack `xox...`) — none
  found outside `node_modules/` (third-party library type definitions,
  not this project's code, and already excluded from Git by
  `node_modules/` in `.gitignore`).
- **All test-file secret-like values are obviously synthetic and
  clearly labeled** (`'test-webhook-secret'`, `'test-secret'`,
  `'test-api-key'`, `waha.internal:3000`) — confirmed by direct
  inspection of `backend/apps/webhooks/tests/test_views.py`,
  `test_authentication.py`, and `backend/apps/sync/tests/test_waha_client.py`.
- **`frontend/.env` and `frontend/.env.example` contain no WAHA
  credential or any secret** — only `VITE_BFF_BASE_URL`. Confirmed
  compliant with `CLAUDE.md` rule 3 (WAHA key never in the frontend).
- **Both `docker-compose.yml` files** (`infrastructure/office/`,
  `infrastructure/tencent/`) use `env_file: .env` exclusively — no
  inline credentials, no hardcoded connection strings. WAHA's service
  definition publishes no port, matching `docs/06-SECURITY.md`.
- **All five `.env.example` files contain placeholders only** —
  confirmed by direct read of every one; no real value present in any of
  them.
- **The previously-exposed incident material does not reappear
  anywhere.** Checked specifically: no `sha512:`-prefixed hash value, no
  `WAHA_DASHBOARD_PASSWORD`/`WHATSAPP_SWAGGER_PASSWORD` *value* (only
  the variable *names*, in prose, describing the incident), and no
  environment-dump content appears anywhere in `docs/generated/`. The
  two reports that narrate the incident
  (`PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md`) describe it without
  reproducing any value, consistent with how it was originally written.
- **No database dumps, `.sqlite3` files, log files, private keys,
  certificates, or IDE-local directories** (`.vscode/`, `.idea/`,
  `.pytest_cache/`) exist anywhere in the current filesystem — a full
  scan for these patterns returned nothing.
- **No secret is referenced by value in any Markdown documentation**,
  including `README.md`, `CLAUDE.md`, and every numbered file in
  `docs/` — all reference credentials only by variable name.

## Files that must NOT be committed

- `backend/.env`
- `bff/.env`
- `frontend/.env`
- Any future `infrastructure/*/. env` (real, filled-in versions — only
  the `.env.example` files should ever be committed)
- Any future `*.env.local` / `*.env.production` / similar variant
  filename (see M2 — not currently protected by pattern, protect before
  such a file is created)

## Git history findings

**Not applicable — no Git repository exists yet** (confirmed at the top
of this report). No commit has ever been made, so no secret can have
been committed historically, and no history-rewrite is needed. This
audit is, functionally, the pre-`git init` check.

## Required remediation before GitHub

1. Replace real phone numbers / LID identifiers / session name
   (`test_session`, `@test_business`) in `docs/12-WAHA-REFERENCE.md`,
   the affected `docs/generated/*.md` files, and
   `backend/apps/webhooks/tests/fixtures.py` /
   `backend/apps/sync/tests/fixtures.py` with synthetic equivalents
   (H1).
2. Decide whether to keep or redact the two real infrastructure IPs
   across the six affected `docs/generated/*.md` files (M2) — a
   judgment call, not made here.
3. Add `.env.*`/`*.env`-style coverage to `.gitignore` before any
   environment-specific `.env` variant is ever created (M2 — see exact
   pattern below).
4. Optional hygiene, not security-blocking: remove or ignore
   `WAHA-Dashboard-Claude-Engineering-Pack-FINAL.zip` (L2); make
   `DJANGO_SECRET_KEY` fail loudly instead of silently falling back in
   non-`DEBUG` mode (L1).
5. After remediation, re-run this same scan pattern once more before
   the first `git init`/`git add`/`git push`, since a second pass is
   cheap and this one was performed by hand rather than by an automated
   secret-scanner.

None of the above require rotating any credential — nothing here is a
credential-exposure finding.

## Recommended `.gitignore` additions

```
# Environment file variants not covered by the exact ".env" match above
*.env
.env.*
!**/.env.example

# Common local-tool artifacts not yet present, but not currently ignored
.vscode/
.idea/
.pytest_cache/
.coverage
*.sqlite3-journal
```

(`.env.*` needs the existing `!**/.env.example` negation repeated/kept
after it, or the example files would stop being tracked — order matters
in `.gitignore`; verify `.env.example` files remain un-ignored after
adding this.)

## Final recommendation

**Do not publish yet — remediate H1 (real PII in docs/fixtures) first;
everything else is optional-but-advisable before the initial push.**
No secret, credential, or key was found hardcoded anywhere, and there is
no Git history to worry about since none exists yet — the technical
"don't leak a key" bar is already met. The one real blocker is that this
repository currently contains real people's phone numbers and a real,
identifiable business's session data as if they were test fixtures. That
is straightforward to fix (synthetic replacements, same shape/format,
zero loss of the documented evidence's technical value) and does not
require any credential rotation or history rewriting, since this would
be the *first* commit, not a cleanup of prior exposure.
