# Inbox/Chat (Canonical Phase 8) — Implementation Report

Implements the 16 explicit decisions from your instruction, following
`docs/generated/INBOX-CHAT-DECISION-REPORT.md`. **Canonical Phase 9 was
NOT started.** No WebSocket/Channels were introduced. The BFF's own
architecture/auth was not redesigned — only reused.

No contradiction with any of the 16 explicit decisions was found during
implementation, so nothing was stopped/escalated — the one real
in-flight discovery (the migration needing to be applied to the real dev
database, Section 9) was a normal completion step, not a decision
conflict.

## 1. Implementation summary

- **Read architecture**: chat list and message history are now real,
  paginated, JWT-`reading`-scoped Django endpoints
  (`GET /api/chats/`, `GET /api/chats/:id/messages/`), called directly
  by the frontend — no BFF involvement, per decision 1.
- **Send**: the Inbox composer calls the **existing, unmodified** BFF
  `sendText` endpoint (`bff/src/routes/messages.ts`) — no second send
  implementation, no BFF change (decision 2/11).
- **Mark as read**: `Chat.last_read_at` (new, nullable `DateTimeField`),
  a chat-level, Django-only, durable flag — never synced to WAHA
  (decision 3). `POST /api/chats/:id/read/`.
- **Real-time**: plain polling, no WebSocket/Channels/ASGI change
  (decision 4) — chat list every 8s, the open conversation's messages
  every 5s, both deliberately conservative and both reusing the
  "silent background refetch + local override state" pattern already
  established by the Session Management phase's `SessionsPage.tsx`.
- **Authorization**: `IsAuthenticated` + a new `HasReadingScope`
  permission (checks the JWT's `scopes` claim for `'reading'`) on all
  three chat endpoints (decision 5) — the first Django endpoints to
  check a JWT scope, mirroring what the BFF already does.
- **Chat discovery**: `WahaClient.fetch_chats()` (wraps the documented
  `GET /api/{session}/chats`) plus a new discovery step inside
  `reconcile_session()` that creates a bare `Chat` row for anything WAHA
  reports that Django doesn't already have, before the existing
  per-chat message loop runs (decision 6). **Live-verified against the
  real, connected WAHA session — see Section 9.**
- **Pagination**: DRF's standard `PageNumberPagination`, added as this
  project's first `DEFAULT_PAGINATION_CLASS` (decision 7); message
  history ordered `-timestamp, -id` for determinism even on tied
  timestamps.
- **Data model**: the smallest possible change — one nullable field,
  one migration (decision 8).
- **Inbox UI**: chat list, selected-chat conversation view, message
  history (oldest-at-top), unread indicator, mark-as-read on open,
  composer, loading/empty/error states for both panes, polling,
  responsive (mobile collapses to one pane at a time), dark/light via
  existing tokens only (decision 9).
- **Media**: shown as an explicit "(preview not available)" line with
  the filename, never a fabricated preview — `storage_reference` is not
  even exposed by the API (decision 10).

## 2. Files changed

Backend:
- `backend/apps/chats/models.py` — added `Chat.last_read_at`.
- `backend/apps/chats/migrations/0002_chat_last_read_at.py` — **new
  migration**.
- `backend/apps/chats/serializers.py` — **new**: `ChatListSerializer`,
  `MessageSerializer`, `MediaReferenceSerializer`.
- `backend/apps/chats/views.py` — **new**: `ChatListView`,
  `ChatMessagesView`, `ChatMarkReadView`.
- `backend/apps/chats/urls.py` — **new**.
- `backend/apps/chats/test_views.py` — **new**: 24 tests.
- `backend/apps/authn/permissions.py` — **new**: `HasReadingScope`.
- `backend/apps/sync/waha_client.py` — added `fetch_chats()`.
- `backend/apps/sync/reconciliation.py` — added `_discover_chats()`,
  wired into `reconcile_session()`, extended `ReconciliationResult`.
- `backend/apps/sync/tasks.py` — surfaced `chats_discovered`/
  `chat_discovery_error` in the task's log line and return value.
- `backend/apps/sync/tests/test_reconciliation.py` — `StubWahaClient`
  and the inline `OverlappingStubClient` both gained a `fetch_chats()`
  method (existing tests broke without this — see Section 6); added
  `ReconciliationChatDiscoveryTests` (7 tests).
- `backend/apps/sync/tests/test_waha_client.py` — added
  `WahaClientFetchChatsTests` (10 tests).
- `backend/config/settings.py` — added `DEFAULT_PAGINATION_CLASS`/
  `PAGE_SIZE` to `REST_FRAMEWORK`.
- `backend/config/urls.py` — wired `path('api/chats/', include(...))`.

Frontend:
- `frontend/src/lib/djangoApi.ts` — added `getChats()`,
  `getChatMessages()`, `markChatRead()` and their response types.
- `frontend/src/lib/bffApi.ts` — added `sendMessage()` (calls the
  existing BFF endpoint; the BFF itself was not touched).
- `frontend/src/pages/InboxPage.tsx` — **rewritten** (was the
  `PlaceholderPage` shell).
- `frontend/src/pages/InboxPage.css` — **new**.

Documentation:
- `docs/07-API-CONTRACT.md` — corrected the stale "chats, messages,
  mark read" line under "Frontend -> BFF" (moved to "Frontend ->
  Django," per decision 1) — a targeted edit, not a rewrite.
- `docs/generated/INBOX-CHAT-IMPLEMENTATION-REPORT.md` — this report.

No `.env`, no BFF source file, no unrelated model/view/page, and no
dependency (`package.json`/`requirements.txt`) was changed.

## 3. Migrations

**One migration created**: `backend/apps/chats/migrations/0002_chat_last_read_at.py`
— adds `Chat.last_read_at` (nullable `DateTimeField`), nothing else.

**Applied to**: the test settings' SQLite database (automatically, via
the test runner) and — after a live-verification 500 error surfaced that
it hadn't been — **the real local dev PostgreSQL database** (`python
manage.py migrate chats`, confirmed successful; see Section 9). No other
migration was created or is pending (`makemigrations --check --dry-run`
→ "No changes detected").

## 4. Backend tests run and results

```
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
→ Ran 243 tests — OK   (206 pre-existing + 37 new, all passing)

python manage.py check
→ System check identified no issues (0 silenced)

python manage.py makemigrations --check --dry-run
→ No changes detected
```

New tests (37), by area:
- `apps/chats/test_views.py` (24): auth/scope enforcement (401/403) on
  all three endpoints; chat-list ordering (most-recent-first, `NULLS
  LAST` explicit — proven with a no-message/older/newest trio); unread
  derivation (never-read, read-then-new-message, read-after-message,
  no-message-yet — all four states); pagination page size and `count`;
  message-history 404 for an unknown chat, deterministic ordering on
  tied timestamps, media inclusion with `storage_reference` confirmed
  **absent**; mark-as-read setting the timestamp and its effect visibly
  flipping `unread` on a subsequent list call; two explicit N+1 query
  regression tests (`CaptureQueriesContext`, asserting the exact query
  count stays constant as row count grows).
- `apps/sync/tests/test_reconciliation.py` (7, new
  `ReconciliationChatDiscoveryTests` class): discovers a new chat;
  prefers the nested `_data.Info.Chat` field over the top-level `id`
  when both are present; does not duplicate an already-known chat; skips
  an entry with no usable identifier without crashing the run; a
  discovery failure is reported (`chat_discovery_error`) but does not
  fail the whole run or block checkpoint advancement; a targeted
  `chat_ids=[...]` run does not trigger discovery at all; a
  newly-discovered chat's message history is reconciled in the **same**
  run, not a separate pass.
- `apps/sync/tests/test_waha_client.py` (10, new
  `WahaClientFetchChatsTests` class): URL encoding, the correct endpoint
  path, API-key-as-header (never in the URL or logged on error), both
  response-shape variants (bare list / `{"chats": [...]}`), rejecting an
  unrecognized shape, non-200/network-error handling, and the
  missing-base-url/missing-api-key fail-fast guards — mirroring the
  exact test structure already used for `fetch_chat_messages`.

**One real bug found and fixed while writing tests, not in new code**:
two existing test doubles (`StubWahaClient` and an inline
`OverlappingStubClient`, both in `test_reconciliation.py`) didn't
implement the new `fetch_chats()` method the real `WahaClient` now has,
so every existing reconciliation test using them broke
(`AttributeError`) the moment `_discover_chats()` was wired in. Fixed by
adding a `fetch_chats()` method to both (empty list by default, so
every pre-existing test's behavior is unaffected — discovery simply
finds nothing for them, exactly as before this change existed). This is
the same class of "the test double didn't implement the full interface
yet" issue as the earlier BFF supertest-dispatch discovery, not a defect
in the discovery logic itself.

**No N+1 regression** was found or introduced — explicitly tested (see
above) via direct query counting, not inferred.

## 5. BFF

**Not modified.** Re-run to confirm, per your instruction:

```
npm run test
→ Test Files 10 passed (10), Tests 99 passed (99)
```

Identical to before this task — `sendText`'s idempotency behavior is
untouched.

## 6. Frontend checks

```
npx tsc -b --noEmit
→ clean, 0 errors

npm run lint (oxlint)
→ 5 warnings, 0 errors — identical pre-existing set (StatusBadge.tsx ×2,
  ThemeContext.tsx, AuthContext.tsx ×2); nothing new from this task

npm run build (tsc -b && vite build)
→ built in 904ms, 0 errors, 0 warnings
```

**No frontend automated test was added** — this project has no test
runner configured for the frontend at all (no `test` script, no
`vitest`/`jest`/`@testing-library` dependency; confirmed again this
task, same finding as the Session Management implementation report).
Consistent with that earlier decision, this task did not bootstrap a
frontend test framework from scratch — out of scope for "the smallest
model change"/"do not add speculative infrastructure" (point 15).

## 7. Live verification (real HTTP + real database, not a browser)

Against the actual running dev servers (Django `:8000`, real
PostgreSQL — not the SQLite test database), using a real JWT for this
environment's dev user (superuser, so it carries every scope including
`reading`):

- `GET /api/chats/` → **first attempt: `500 internal_error`.**
  Diagnosed immediately: `python manage.py showmigrations chats` showed
  `0002_chat_last_read_at` was **not yet applied** to the real dev
  database (only the SQLite test database had it, applied automatically
  by the test runner). Ran `python manage.py migrate chats` — confirmed
  successful. Re-tested: **`200`**, real data returned correctly.
- `GET /api/chats/:id/messages/` → `200`, real data.
- `POST /api/chats/:id/read/` → `200`, `last_read_at` set; confirmed a
  follow-up `GET /api/chats/` reflected `unread: false` for that chat.
- No `Authorization` header → `401`, as expected.
- CORS preflight for `Origin: http://localhost:5173` on
  `GET /api/chats/` → `200` with `Access-Control-Allow-Origin:
  http://localhost:5173` present — the new endpoints are reachable from
  the real frontend origin, no CORS gap.

This is a genuine finding, not hidden: **a migration created during this
task was initially only applied to the test database, not the real dev
database** — a normal, expected step (every migration needs an explicit
`migrate` run against each real database it targets) that I completed as
part of finishing this task, not a design defect.

## 8. Live chat-discovery verification against the real, connected WAHA session

With your prior confirmation that `no_epahari` is the real, currently-
connected session (established in the Session Management WAHA config
audit), and given reconciliation is this project's own existing,
designed-to-be-safely-repeatable operation (additive only — it never
deletes anything), I ran one real reconciliation pass to verify the new
discovery code against actual production WAHA data, not just mocks:

```
reconcile_session('no_epahari', limit=20, max_pages=2)
→ chats_discovered: 4
→ chat_discovery_error: None
→ chats_processed: 5
→ messages_inserted: 17
→ had_error: False
```

**This found 4 real chats WAHA had that Django had never received a
webhook for, and correctly pulled their real message history in the
same run** — confirmed by re-querying `GET /api/chats/` and
`GET /api/chats/:id/messages/` afterward: real chat entries and at least
one real inbound message rendered correctly through the new serializer
end-to-end. (I did not reproduce the message's actual text in this
report out of respect for the third party who sent it — only confirmed
the pipeline delivers real content correctly, which it does.)

**Two things observed, both pre-existing and correctly left alone, not
"fixed" here:**
- The chat list now also shows entries with `last_message_at: null` and
  several distinct identifier forms (`@lid`, `@s.whatsapp.net`, `@c.us`)
  that likely represent the *same* real contact under different
  provider-reported chat IDs. This is the exact, already-documented
  identity-fragmentation limitation from `docs/12-WAHA-REFERENCE.md`
  ("the same real-world contact can appear under two different primary
  chat identifiers... no safe merge rule is supported by the evidence,
  so none is implemented") — now simply observed again with real data,
  not a new bug and not something this task invents a merge rule for.
- `status@broadcast` (WhatsApp's own built-in status-updates pseudo-chat)
  appears in the discovered list, because WAHA's chat-list endpoint
  genuinely reports it. Not filtered out — no document asks for that
  filter, and inventing one would be exactly the "silently make
  additional product decisions" this task says not to do. Flagged here
  as an observed, not-yet-decided UI/product question, not fixed.

## 9. What could not be verified — no browser available

**No browser verification was performed and none is claimed.** Section
7/8 above prove the API/data layer works correctly end-to-end against
real infrastructure; nothing about actual rendering, click-through
interaction, dark/light theme, or responsive layout was observed. See
the manual checklist below.

## 10. Known limitations

- No contact-info third pane — not required by this task's explicit UI
  scope (point 9's list doesn't include it).
- No media preview/serving — `MediaReference.storage_reference` has no
  defined public-serving mechanism anywhere in this project; the UI
  says so explicitly instead of guessing at one.
- After a successful send, no local/optimistic message bubble is shown
  — the real message only appears once it round-trips through WAHA's
  webhook back into Django's durable store (picked up by the next poll
  tick). A brief "Message sent" confirmation is shown instead. This is
  deliberate (point 12: never fabricate a message), not an oversight.
- `Message.status` is always blank in this database — the existing
  webhook/reconciliation parser has never populated it (confirmed by
  reading `apps/webhooks/parsing.py` again this task) — so no delivery/
  read-tick indicator is shown in the composer/thread; there's no real
  data for one.
- The chat-identity-fragmentation and `status@broadcast` items from
  Section 8 remain open, pre-existing, documented questions, not bugs
  introduced or fixed by this task.
- Real-time delivery remains polling-only, by explicit decision
  (decision 4) — not a limitation relative to this task's scope, stated
  here for completeness.

## 11. Manual browser testing checklist

**Important — read before testing Send**: your `no_epahari` session is
a real, connected WhatsApp number, and the chat list now includes real
contacts (including at least one who messaged asking about vehicle tax).
**Sending a test message from the Inbox composer sends a real WhatsApp
message to whichever real chat is selected.** Test "Send" only against a
chat you're certain is safe to message (e.g. your own number, or a chat
you own), not an arbitrary real contact from the discovered list.

1. Open Inbox (sidebar nav) — confirm the chat list loads and shows the
   real chats (there are 8 as of this report; several will show an
   unread indicator).
2. Click a chat — confirm it opens on the right, its unread indicator
   disappears, and this persists after a page refresh (durable, not just
   local UI state).
3. Confirm message history renders oldest-at-top; if a chat has more
   than 20 messages, confirm "Load older messages" appears and works.
4. Confirm a chat with zero messages shows a proper empty state, not a
   blank area.
5. **Only in a safe chat**: type a message, send it, confirm the
   "Message sent" confirmation appears, and — after roughly the 5s poll
   interval — confirm the real message eventually appears in the thread
   once the webhook round-trip completes.
6. Leave the Inbox open for ~10–15s and confirm the chat list/open
   conversation update on their own (new activity, if any occurs)
   without a manual refresh.
7. Resize the browser to a narrow/mobile width — confirm the layout
   collapses to one pane at a time with a working "Back" button.
8. Test dark mode and light mode.
9. Check the browser Console for errors.
10. Check the Network tab — confirm chat list/message requests go to
    Django (`:8000`), the send request goes to the BFF (`:8080`), and
    nothing goes directly to WAHA from the browser.
11. Navigate away from Inbox and back — confirm polling stops while
    away and resumes correctly, with no duplicate/leaked intervals
    (e.g. watch the Network tab for doubled request cadence after
    navigating back and forth a few times).

---

Do not start another phase automatically after this task.
