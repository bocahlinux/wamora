# Local-Development `.env` Auto-Loading Fix

A narrow backend ergonomics fix — not an architecture change, not a new
coding phase. Phase 8 was not started; `frontend/` and `bff/` were not
touched (confirmed by file-modification-time check, zero results).

## 1. Repository-evidence review (performed before any change, as instructed)

**Verdict: the change is consistent with the existing contract — proceed,
don't stop.**

- `README.md`'s own documented local-dev sequence (`cp .env.example
  .env` immediately followed by `python manage.py migrate`, no
  `export`/`source` step shown) already assumed `.env` would be picked up
  automatically. That assumption was factually false until this fix —
  this is closing a gap between documentation and behavior, not
  introducing a new convention.
- `docs/CLAUDE.md`, `docs/00-MASTER-SPEC.md`, `docs/06-SECURITY.md`
  mandate *where* secret values must live (environment variables, never
  hardcoded) but say nothing about *how* the process environment gets
  populated — that's left as an implementation detail, not a decision
  already made and closed.
- No document anywhere states environment injection must be external-only
  or that `.env` auto-loading is intentionally out of scope. Searched
  specifically for this before proceeding; found nothing.
- `backend/.dockerignore` already excludes `.env` from the Docker build
  context, and both `docker-compose.yml` files already inject
  configuration via `env_file:` directly into the container process —
  meaning Docker/production already get their environment through a
  completely different, already-correct mechanism this fix doesn't touch
  at all.

## 2. What was implemented

**`backend/config/env.py`** (new) — a small, directly-testable function:

```python
def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    from dotenv import load_dotenv
    load_dotenv(path, override=False)
```

`override=False` is `python-dotenv`'s own default — an already-exported
shell variable always wins over the same key in `.env`. A missing file
is a silent no-op, never an error (the expected, normal case in
Docker/production).

**`backend/config/settings.py`** — three lines added right after
`BASE_DIR` is defined, before any `os.environ.get(...)` call:

```python
from config.env import load_env_file
load_env_file(BASE_DIR / '.env')
```

**`backend/requirements.txt`** — added `python-dotenv==1.0.1`, the only
new dependency. No other package was added or upgraded.

**`README.md`** — one clarifying paragraph added to the Backend local-dev
section, stating that `.env` now loads automatically, that an
already-exported shell variable still wins, and that Docker/production
never depend on `backend/.env` being present — so a reader understands
*why* the existing `cp .env.example .env` → `python manage.py migrate`
sequence (unchanged) now actually works as written.

## 3. Requirements checklist (from the task)

- [x] `backend/.env` loads automatically for a bare `python manage.py
  ...` invocation — verified live (Section 4).
- [x] Real `.env` files remain gitignored — untouched, still covered by
  the root `.gitignore`'s `.env`/`*/.env`/`**/.env`/`*.env`/`.env.*`
  patterns (unchanged from the earlier GitHub-publication remediation
  round).
- [x] `.env.example` remains tracked — untouched.
- [x] Docker behavior unchanged — no `Dockerfile`, `docker-compose.yml`,
  or `.dockerignore` was modified; verified the exclusion is still in
  place.
- [x] Production does not silently depend on `.env` — proven both by the
  `.dockerignore` exclusion (the file can't be present in the image) and
  by a direct unit test that a missing file is a true no-op (Section 5).
- [x] Already-exported environment variables take precedence — verified
  at both the unit level and the real `settings.py` level (Section 4).
- [x] No secret was added to source code or documentation — `config/env.py`
  and the README addition contain no credential value, only the
  mechanism.

## 4. Live verification (bare invocations, no manual env export)

Run exactly as a developer would, with no `_load_env.py`-style shim and
no manual `export`:

```
$ python manage.py check
System check identified no issues (0 silenced).

$ python manage.py makemigrations --check --dry-run
No changes detected
```

Before this fix, the exact same bare `python manage.py check` failed
with `settings.DATABASES is improperly configured. Please supply the
NAME...` (the originally-reported symptom) — this is the same command,
now succeeding with zero manual setup, which is the concrete proof the
gap is closed.

**Precedence, verified at the real `settings.py` level** (not just the
isolated unit, using a harmless non-secret value to avoid printing
anything sensitive):

```
$ DB_NAME=shell_override_wins python -c "... settings.DATABASES['default']['NAME'] ..."
PRECEDENCE_OK: shell-exported DB_NAME beat backend/.env
```

## 5. Tests added

`backend/apps/core/test_env_loading.py` — 4 new tests, testing the exact
function `settings.py` calls (not a re-implementation of it):

- `test_loads_values_from_a_present_file` — a temp `.env` file's values
  land in `os.environ`.
- `test_already_exported_environment_variable_takes_precedence` — a
  pre-set `os.environ` value is not overwritten by the same key in the
  file.
- `test_missing_file_is_a_silent_no_op` — a nonexistent path never
  raises and never mutates `os.environ` at all (the production-safety
  requirement, unit-tested directly).
- `test_blank_and_comment_lines_are_tolerated` — ordinary `.env` file
  syntax (blank lines, `#` comments) doesn't break loading.

## 6. Full checks run

- **Django test suite** (`DJANGO_SETTINGS_MODULE=config.settings_test`,
  the project's existing SQLite override for this sandbox — real
  PostgreSQL `CREATEDB` is still unavailable here, a pre-existing,
  unrelated limitation this task doesn't touch): **172 tests, 172
  passing** (168 pre-existing, unchanged + 4 new).
- **`manage.py check`**: clean, run bare, against real `config.settings`
  (Section 4).
- **`manage.py makemigrations --check --dry-run`**: `No changes
  detected`, run bare (Section 4). No model or migration was touched —
  confirmed by this check alone being sufficient evidence, as in every
  prior round.
- **Lint**: no Python linter is configured anywhere in this repository
  (no `flake8`/`ruff`/similar in `requirements.txt` or any config file at
  any point this project has been worked on) — none exists to run.

## 7. `backend/.env` — confirmed unmodified

The real `backend/.env` was never written to by this task — only read,
via `load_dotenv`. Its variable count (14) is unchanged from every prior
check this session. Its filesystem modification time shifted (to the
moment the precedence/check commands in Section 4 ran) purely as a
side effect of being *read*; content is unaffected. No value in it was
printed anywhere in this session.

## 8. Scope confirmation

Only `backend/config/env.py` (new), `backend/config/settings.py`,
`backend/requirements.txt`, `backend/apps/core/test_env_loading.py`
(new), and `README.md` were modified. No database model, no migration,
no PostgreSQL configuration, no Docker file, no live infrastructure,
`frontend/`, or `bff/` was touched — confirmed directly by
file-modification-time checks returning zero results for the latter two.
Phase 8 was not started.
