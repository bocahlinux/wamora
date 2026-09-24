# INTERNAL_SERVICE_KEY Fingerprint Audit — Root Cause Found (Read-Only)

Follow-up to
[`INTERNAL-SERVICE-AUTH-AUDIT-REPORT.md`](INTERNAL-SERVICE-AUTH-AUDIT-REPORT.md).
You confirmed `echo $env:INTERNAL_SERVICE_KEY` is empty in both the BFF's
and Django's interactive terminals, ruling out that report's
"stray shell export" hypothesis. This task investigated further and
found the actual mechanism. **Read-only** — no source code, `.env`,
database, or WAHA state was changed; no WhatsApp message was sent; no
internal endpoint was invoked live; the secret value itself is never
printed anywhere below — only lengths and SHA-256 fingerprints.

## Root cause

**CONFIRMED: two separate `manage.py runserver` processes are
simultaneously bound and LISTENING on port 8000 right now**, one
long-lived and stale, one brand new:

```
netstat -ano | findstr :8000 LISTENING
  TCP    0.0.0.0:8000    LISTENING    46352   <- new, ~1 minute old
  TCP    0.0.0.0:8000    LISTENING    69756   <- old, since 21:36:55
```
Confirmed by two independent methods (`Get-NetTCPConnection` and native
`netstat`), so this is not a tooling artifact.

**The old process's full lineage**:
```
PID 6960  (manage.py runserver 0.0.0.0:8000)  started 2026-09-24 21:36:55
  └─ PID 69756 (same command, RUN_MAIN child)   started 2026-09-24 22:36:58
```
`backend/.env` was last written at **22:53:24** — **over an hour after**
watcher PID 6960 first started (21:36:55), and even the child restart at
22:36:58 predates it by 17 minutes. This process tree's environment was
seeded before the current `INTERNAL_SERVICE_KEY` value ever existed on
disk.

**A second, newer process tree** appeared in this same snapshot, using
the project's own virtualenv interpreter for the first time in this
audit's evidence (everything before this was the system Python at
`C:\Users\asus\AppData\Local\Programs\Python\Python310\python.exe`):
```
PID 57936 (D:\...\backend\venv\Scripts\python.exe)  started 23:21:23
  └─ PID 69784 (system python.exe)                   started 23:21:23
      └─ PID 58344 (venv python.exe)                 started 23:21:24
          └─ PID 46352 (system python.exe)           started 23:21:24
```
Four levels deep within one second strongly suggests several rapid
autoreload restarts right after this tree's own launch — but critically,
**it did not replace the old one**: PID 69756 is still LISTENING. On a
normal single-server setup, a second process trying to bind the same
port would fail outright ("address already in use"); here, both show as
LISTENING, meaning the OS is (at least in this session) accepting
connections to port 8000 on **either** process, unpredictably from an
outside caller's perspective. **This alone is a sufficient explanation
for confusing, seemingly-inconsistent behavior**, independent of any
environment-variable question.

**BFF is currently not running at all**: port 8080 has **zero**
listeners right now (confirmed by both `Get-NetTCPConnection` and
`netstat` — no match). The 403 log lines you pasted came from whichever
BFF process was alive *at that moment* (matching the long-lived
`tsx watch` processes below, started 18:59:23) — that process is no
longer bound to the port at the time of this audit.

## Mechanism (why a stale process would show 403 specifically)

`backend/config/env.py::load_env_file()` calls
`load_dotenv(path, override=False)` — **never overwrites an
`os.environ` key that's already present**, even an empty one. Django's
`runserver` autoreloader spawns each restart's child as a subprocess
that inherits its **watcher's** environment (`os.environ.copy()`-style),
not a fresh read of the current shell — so every child ever spawned
from watcher PID 6960 (including 69756) carries forward whatever
`INTERNAL_SERVICE_KEY` value (or absence of one) existed in **that
watcher's own environment at 21:36:55**, regardless of how many times
`backend/.env` is edited afterward, and regardless of how many
*autoreload-triggered* restarts happen — only a full kill of the
**watcher itself** (not just its child) followed by a genuinely fresh
`python manage.py runserver` invocation would pick up today's edited
value. This exact mechanism was already documented in the prior audit;
what this task adds is **direct proof that this specific stale process
is still alive and still holds the port** — not merely a theoretical risk.

## Fingerprint table (A/B/C/D)

| | Source | SHA-256 | Length | Status |
|---|---|---|---|---|
| **C** | `backend/.env` file (current, on disk) | `d0d557f3...aebe2c` | 64 | Read directly, safe |
| **D** | `bff/.env` file (current, on disk) | `d0d557f3...aebe2c` | 64 | Read directly, safe |
| **B** | `INTERNAL_SERVICE_KEY` as loaded by the **live** Django process actually answering requests | **Not obtainable** | Unknown | See below |
| **A** | `INTERNAL_SERVICE_KEY` as loaded by the **live** BFF process | **Not obtainable — BFF is not running** | N/A | Port 8080 has no listener right now |

**C = D — confirmed** (full 64-byte match, same fingerprint).

**Why B cannot be fingerprinted from outside**: there is no in-repo
mechanism to read another running process's environment block without
either (a) instrumenting code to print/hash it and log the result (would
require your prior approval, per your own instruction 10 — not sought,
since the process-identity evidence above already explains the symptom
without it), or (b) invoking a live endpoint (forbidden this task). What
**is** proven, without reading any value: PID 69756's watcher predates
the current file content by over an hour, so **B ≠ C is the necessary
conclusion of the process-lineage timing alone**, independent of ever
reading B's actual bytes.

**A** cannot be checked at all right now, for a much simpler reason:
the BFF process is not running.

## Answering your specific questions

- **File Django reads**: `backend/.env`, via `config/env.py::load_env_file()`
  called from `config/settings.py` — confirmed unchanged from the prior
  audit; not the source of the problem (C matches D).
- **File BFF reads**: `bff/.env`, via Node's `--env-file=.env` flag
  (`bff/package.json`'s `dev` script, confirmed from the live process's
  own command line: `tsx watch --env-file=.env src/index.ts`) — also not
  the source of the problem, and currently moot since that process isn't
  running.
- **Does dotenv actually load `INTERNAL_SERVICE_KEY`?** Yes, mechanically
  — `load_dotenv(override=False)` will set it **the first time** a given
  process's `os.environ` doesn't already have it. The bug is not that
  loading fails; it's that a *stale, still-running* process from before
  today's fix never got a chance to load the current value, and nothing
  has told it to since.
- **When does each process read its environment?** Once, at that
  specific process's own startup (or, for an autoreload-spawned child,
  inherited from its watcher's startup) — never re-read afterward.
- **Any other env loader changing the value afterward?** No evidence of
  one — `grep` across the repo found no other file referencing
  `INTERNAL_SERVICE_KEY` outside the two `.env` files and their `.example`
  counterparts (checked in the prior audit).
- **Does `HasInternalServiceKey` compare against something other than
  `settings.INTERNAL_SERVICE_KEY`?** No — re-confirmed unchanged from the
  prior audit's code reading: `settings.INTERNAL_SERVICE_KEY` (`os.environ.get('INTERNAL_SERVICE_KEY', '')`,
  read once at process startup) is the only source `HasInternalServiceKey.has_permission()`
  compares against.
- **Whitespace/BOM/hidden characters?** Not the differentiator here — C
  and D are byte-identical to each other by direct SHA-256 comparison;
  the divergence is about *which running process* the BFF's requests
  actually land on, and what environment *that specific process*
  inherited at *its own* startup — a process-lifecycle question, not a
  file-encoding one.

## Is the problem in `.env`, dotenv loading, the runtime process, or the comparison/auth logic?

**The runtime process.** Not the file content (C = D, confirmed). Not
the dotenv mechanism itself (working exactly as documented). Not the
comparison/auth logic (`hmac.compare_digest` against `settings.INTERNAL_SERVICE_KEY`,
already verified correct in the prior audit). The problem is that **an
old server process from before today's `.env` fix was never fully
terminated**, is still answering on port 8000 alongside (at least) one
newer attempt, and the BFF side is currently not running at all.

## Recommended minimal fix (NOT implemented)

Pure process hygiene — no code, config, or `.env` change:
1. **Fully stop every Django process bound to port 8000.** From an
   elevated/appropriate terminal: identify all PIDs with
   `netstat -ano | findstr :8000` and stop each one (e.g.
   `Stop-Process -Id 69756 -Force`, `Stop-Process -Id 6960 -Force`, and
   the same for the newer 57936/69784/58344/46352 tree if it's not the
   one you intend to keep) — do not rely on Ctrl+C alone in a terminal
   window you're unsure is the right one, since that only stops the
   watcher your Ctrl+C reaches, not necessarily every process holding
   the port.
2. **Verify the port is actually free**: `netstat -ano | findstr :8000`
   should return nothing.
3. **Start exactly one** `python manage.py runserver 0.0.0.0:8000` from
   a single, known terminal, using whichever Python interpreter you
   intend (system vs. `backend/venv` — pick one consistently; running
   both is itself a likely source of future confusion, e.g. if the venv
   has different installed package versions).
4. **Re-verify**: `netstat -ano | findstr :8000` should show exactly one
   PID, and its process-start time should now be *after* this cleanup.
5. **Do the same check for the BFF** (currently not running at all —
   start it fresh, then confirm `netstat -ano | findstr :8080` shows
   exactly one PID).
6. Only then, re-test one outbound send and watch for the
   `[djangoClient]`/`[messages]` diagnostic lines added in the previous
   task.

Not implemented, per your instruction to audit only.

---

No source code, `.env`, database, or WAHA session was changed. No
WhatsApp message was sent. No internal endpoint was invoked live. The
secret value was never printed — only lengths and SHA-256 fingerprints
of file contents. Not proceeding to Phase 9 or any other task —
stopping here as instructed.
