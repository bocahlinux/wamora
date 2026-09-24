# Phase 4 — Reconciliation & History Sync

> **Update (pagination verification round)**: after this report was first
> written, the project operator performed a live REST pagination
> comparison directly against the deployed WAHA instance and shared the
> results. Sections 4–6, 9, 13, 14, and 19 below have been revised
> accordingly — single-page fetch is now bounded multi-page pagination
> using `limit`+`offset`, confirmed working. Everything else (identity
> handling, checkpoint semantics, transaction/failure behavior, the real
> PostgreSQL verification) is unchanged and still accurate.

## 1. Phase objective

Implement reconciliation: recover messages not received through the
webhook path by fetching WAHA REST history, comparing stable provider
message IDs against existing `Message` rows, inserting only what's
missing, and advancing `SyncCheckpoint` — repeatable, idempotent, never
creating duplicate durable records (`docs/05-WEBHOOK-SYNC-DESIGN.md`).

## 2. Documentation reviewed

`docs/00-MASTER-SPEC.md`, `docs/04-DATA-MODEL.md`,
`docs/05-WEBHOOK-SYNC-DESIGN.md`, `docs/12-WAHA-REFERENCE.md`,
`docs/15-CODING-PHASES.md`, `docs/generated/PHASE-3-WEBHOOK-INGESTION.md`,
`docs/generated/PHASE-3-LIVE-VERIFICATION.md`,
`docs/generated/PHASE-2.5-LID-JID-VERIFICATION.md` — all re-read in full
before writing any code.

## 3. Existing implementation reviewed

`apps/waha_sessions/models.py`, `apps/chats/models.py` (Chat/Contact/Message),
`apps/webhooks/models.py` (WebhookEvent), `apps/sync/models.py`
(SyncCheckpoint), `apps/webhooks/parsing.py`, `apps/webhooks/services.py`,
existing constraints/indexes (all Phase 2, unchanged), and the full Phase 3
test suite. No existing model was redesigned. One small, mechanical,
non-behavioral change: `apps/webhooks/services.py`'s `_persist_message` was
renamed to `persist_message` (dropped the underscore) so Phase 4 could
import and reuse it directly rather than duplicating its logic — updated
its one existing test reference accordingly. No other change to Phase 3
files.

## 4. WAHA endpoint used

`GET /api/{session}/chats/{chatId}/messages?limit=N` — the only endpoint
pattern this project has ever had confirmed evidence for
(`docs/12-WAHA-REFERENCE.md`, `docs/generated/PHASE-3-LIVE-VERIFICATION.md`).
No other endpoint path or response format was invented.

## 5. Actual pagination mechanism

**CONFIRMED BY LIVE EVIDENCE.** The project operator ran a direct live
comparison against the real deployment (session `test_session`, chat
`000000000000000@lid`):

- `?limit=2` → the 2 newest messages.
- `?limit=2&offset=2` → the next 2 older messages — no overlap, no gap
  with the previous call.
- `?limit=2&page=2` → **identical** result to `?limit=2` — `page` is
  silently ignored by this WAHA version and must never be used.
- Ordering is confirmed **newest-first**.

**Implementation, updated accordingly**: `WahaClient.fetch_chat_messages`
now accepts `offset` (still never sends `page`). The multi-page loop
itself lives in `apps/sync/reconciliation.py::_iter_chat_history_pages` —
deliberately a generator, yielding one page at a time so each page's
messages are persisted immediately after that page is fetched, rather
than collecting every page before persisting anything. This matters for
failure safety: if page 2's fetch fails, page 1's messages — already
fetched and already persisted — are not lost (see Section 12). Bounded by
three independent, safe stopping conditions, never an unlimited scan:
1. A page returns fewer than `limit` items (end of available history).
2. The oldest message in a page is at or before the **pre-run** checkpoint
   watermark (Section 10) — newest-first ordering makes this a valid
   signal that everything from here backward is already synced. Uses the
   watermark as it was *before* this run started, never the value being
   built up during the run itself.
3. `max_pages` (default 10) — a defensive hard cap, independent of the
   other two, for a chat with no prior checkpoint and substantial history.

`offset` is purely a local loop variable inside `_iter_chat_history_pages`
— never returned, never stored anywhere, never touches `checkpoint_value`
(Section 10 confirms `checkpoint_value` remains a timestamp watermark
only, per your explicit instruction not to use offset as the persistent
checkpoint).

## 6. Actual response structure

**CONFIRMED BY LIVE EVIDENCE**, from the same live comparison: a bare
JSON array of message objects (no `{"messages": [...]}` wrapper) —
`WahaClient` already handled this shape (and still defensively accepts a
wrapped form too, harmless since it's never hit). Field-level structure
matches the webhook payload shape exactly, confirming `parse_message` is
safe to reuse as-is for REST-sourced messages (Section 8) — re-confirmed
by this round's evidence across several real messages, not just the one
message checked previously. The real responses also include additional
fields this project doesn't currently use (`source`, `to`, `hasMedia`,
`ack`, `_data.Info.PushName`, `VerifiedName`, etc.) — recorded in
`docs/12-WAHA-REFERENCE.md` for awareness, not needed by the current
parser.

## 7. Provider message ID rule

**CONFIRMED BY LIVE EVIDENCE** (from the prior live-verification round,
re-applied here): `messages[].id` and the webhook's `payload.id` are the
same value, byte-for-byte, and distinct from `_data.Info.ID`.
`Message.provider_message_id` uses `payload.id`/`messages[].id` exactly —
no transformation, no prefix stripping, no substitution of `Info.ID`.
Enforced by reusing `apps.webhooks.parsing.parse_message` unmodified
(it already implemented this rule from Phase 3), and directly tested:
`test_info_id_is_not_substituted_for_messages_id`,
`test_provider_message_id_preserved_exactly`.

## 8. Chat/contact identity handling

**DOCUMENTED DESIGN, reused exactly from Phase 2.5/Phase 3** — no new
normalization logic was written. `persist_message` (shared between
webhook ingestion and reconciliation) stores `Chat.provider_chat_id` /
`Contact.provider_contact_id` verbatim from WAHA's primary fields, treats
`SenderAlt` as optional `phone_number` metadata only, and never creates a
`Contact` from an outbound message's `Sender`. The confirmed identity-
fragmentation limitation (same phone number under two different `Chat`
identities — `docs/12-WAHA-REFERENCE.md`) is explicitly **not** addressed
by merging — tested directly
(`test_phone_number_not_used_as_identity_key`) to prove reconciliation
does not attempt to collapse the two chats.

## 9. Reconciliation algorithm

`apps/sync/reconciliation.py::reconcile_session(session_name, chat_ids=None, limit=100, max_pages=10, waha_client=None)`:

1. Look up the `WahaSession`; get-or-create its `SyncCheckpoint`, mark
   `status=running`. Read the checkpoint's pre-run `checkpoint_value` once,
   as the pagination stopping boundary (Section 5, condition 2).
2. For each already-known `Chat` row for that session (optionally narrowed
   to `chat_ids`) — **never** discovers new chats via a general chat-listing
   call, per "do not implement mass synchronization blindly" — iterate its
   bounded history pages via `_iter_chat_history_pages`.
3. For each page, for each message: parse with the shared `parse_message`;
   if parsing fails, record the failure and continue (no crash, no
   fabricated data); otherwise call the shared `persist_message` inside
   its own `transaction.atomic()` block — `DuplicateMessage` (from the
   DB's existing unique constraint) is caught and counted as "skipped",
   not an error. Persistence happens immediately per page, not after all
   pages are collected (Section 5).
4. If a chat's fetch fails partway through pagination, whatever pages were
   already fetched and persisted before the failure remain — only that
   chat is excluded from `chats_processed` and the run overall is marked
   as having an error.
5. After all chats: if anything failed, mark the checkpoint `status=error`
   with a summary in `last_error` and **do not advance `checkpoint_value`**.
   If everything succeeded, mark `status=ok` and advance `checkpoint_value`
   to the latest message timestamp seen across the run.

Exposed via `python manage.py reconcile <session> [--chat ID] [--limit N]
[--max-pages N]` for manual/future-Celery invocation (Celery wiring itself
is Phase 5, not built here).

## 10. Checkpoint semantics

**DOCUMENTED DESIGN — confirmed by you this round**, since
`docs/04-DATA-MODEL.md` does not define `checkpoint_value` and your Phase
4 instructions explicitly required stopping rather than silently choosing.
Asked directly; you selected: **`checkpoint_value` is a session-scoped
watermark — the latest message timestamp from the most recent fully
successful run.** No schema change was needed or made. Durable-record
correctness (no duplicates) is guaranteed entirely by the existing
`(session, provider_message_id)` constraint, independent of this value —
it is purely an optimization marker for future incremental use, not a
correctness mechanism.

## 11. Transaction behavior

`WebhookEvent`/`WahaSession` creation (already Phase 3 behavior) commits
immediately, outside any wrapping transaction. Each message's
`Chat`/`Contact`/`Message` persistence happens inside its own
`transaction.atomic()` block (one per message, not one for the whole
chat/run) — a failure on one message cannot corrupt or roll back
previously-persisted messages in the same run, and cannot leave a
partial `Contact`-without-`Chat` or `Chat`-without-`Message` for the
message that failed. Checkpoint advancement happens once, after the
entire run, and is skipped entirely on any error.

## 12. Failure/retry behavior

- **WAHA unreachable for a chat**: caught as `WahaClientError`. Updated
  behavior: any pages already fetched and persisted *before* the failure
  (e.g. page 1 of a 3-page fetch) remain in the database — only the
  failure point onward is lost, not the whole chat's progress for that run
  (verified: `test_failure_mid_pagination_preserves_inserted_messages_but_marks_error`).
  Checkpoint still marked `error`, `checkpoint_value` unchanged,
  `last_run_at` still recorded (verified:
  `test_failed_fetch_does_not_advance_checkpoint`).
- **A message fails to parse**: recorded, skipped, does not crash the run
  or fabricate data (verified: `test_partial_message_parse_failure_marks_run_as_error`).
- **Retry after failure**: re-running `reconcile_session` after an error
  reprocesses safely — already-inserted messages are recognized as
  duplicates (DB constraint), the checkpoint recovers to `ok` on the next
  clean run (verified: `test_error_does_not_falsely_mark_success_and_retry_recovers`).
- **Nothing is ever marked successfully synchronized while errors are
  outstanding** — checkpoint `status`/`checkpoint_value` logic makes this
  structurally impossible, not just conventionally avoided.
- **Overlapping/duplicate pages** (not observed in practice, but not
  something to trust blindly): even if WAHA ever returned the same
  message across two pages, the DB constraint absorbs it silently
  (verified: `test_duplicate_ids_across_pages_not_duplicated`).

## 13. Unit test results

**114 tests total, all passing** (69 carried over from Phases 1–3, 45 in
`apps.sync` for Phase 4): `python manage.py test apps` via the
established test-only SQLite settings (`config/settings_test.py`,
unchanged from Phase 2). Pagination-specific additions this round: 3 for
`WahaClient` (`offset` sent correctly, defaults to 0, `page` never sent),
12 for reconciliation pagination (first page offset, correct offset
sequence across pages, all pages inserted, stop-on-short-page,
empty-first-page, partial-last-page, `max_pages` cap enforced —
"bounded, not unlimited", stop-at-checkpoint-watermark, idempotent
re-run with pagination, duplicate-across-pages absorbed, offset never
written to `checkpoint_value`, failure-mid-pagination preserves prior
pages). All other Phase 4 tests (identity handling, checkpoint semantics,
transaction/session-scoping, cross-path consistency) carried over
unchanged and still passing.

## 14. Live verification result

**Pagination mechanism: CONFIRMED BY LIVE EVIDENCE** (Section 5) — the
project operator performed the live REST comparison directly. This is
qualitatively different from every prior round: it is the first time
actual authenticated WAHA behavior has been confirmed anywhere in this
project.

**Everything else about live WAHA access: still not independently
verified by this session** — no real `WAHA_API_KEY` value has been
provided to this session at any point (this round included), so no
authenticated call was made *by this session itself*. Webhook HMAC
auth, `sendText`/outbound behavior, and group-chat behavior remain
unverified, unchanged from prior rounds.

## 15. PostgreSQL verification result — VERIFIED FROM REAL DEPLOYMENT

This is new and is the most significant result of this phase. Using the
real PostgreSQL connection details you placed in `backend/.env`
(read and used, never printed — parsed directly in Python, bypassing the
shell entirely after `.env`'s unquoted special characters broke bash's
`source`):

- `SELECT current_database(), current_user, version()` confirmed a live
  connection: database `waha_monitoring`, user `waha`, PostgreSQL 17.4.
- `python manage.py migrate` applied all 6 app migrations (plus Django's
  own contrib apps) cleanly against this real database — this is the
  first time this project's schema has ever been applied to real
  PostgreSQL rather than SQLite or a placeholder connection.
- Ran the real committed code (`ingest_webhook`, `reconcile_session` with
  a stub WAHA client serving the real captured payloads) inside one
  top-level transaction against this real database: inbound message
  ingested via the webhook path, outbound message recovered via
  reconciliation, both correctly linked to the same `Chat`/`Contact`,
  `SyncCheckpoint` correctly advanced to `status=ok` with
  `checkpoint_value` set to the later message's timestamp. Re-running
  both paths again confirmed **zero duplicate rows** — idempotency holds
  against real PostgreSQL, not just SQLite.
- The entire verification ran inside a transaction that was then rolled
  back — confirmed by a post-rollback count query showing zero rows for
  the verification session. **No data was left in the real database**, no
  table was truncated, no existing data was touched.

This directly resolves the "Django → PostgreSQL live persistence" and
"duplicate webhook/reconciliation against a real database" items that
were unverified in every prior round.

**Re-verified this round** with the updated multi-page pagination code,
same rolled-back-transaction methodology: a 7-message synthetic history
was reconciled with `limit=3` against the real database, correctly
fetched across 3 pages (offsets 0, 3, 6), all 7 messages persisted, the
checkpoint advanced to the correct watermark, and a re-run made exactly 1
call (correctly stopped immediately at the watermark boundary) and
inserted 0 new messages. Rolled back afterward — zero rows left.

## 16. Files created

- `backend/apps/sync/waha_client.py`
- `backend/apps/sync/reconciliation.py`
- `backend/apps/sync/management/__init__.py`, `management/commands/__init__.py`, `management/commands/reconcile.py`
- `backend/apps/sync/tests/__init__.py`, `tests/test_models.py` (moved from the old `tests.py`, unchanged), `tests/test_waha_client.py`, `tests/test_reconciliation.py`, `tests/fixtures.py`

## 17. Files modified

- `backend/apps/webhooks/services.py` — `_persist_message` → `persist_message` (rename only, no behavior change)
- `backend/apps/webhooks/tests/test_ingestion.py` — updated to the new name
- `backend/apps/webhooks/parsing.py` — `_parse_timestamp` → `parse_timestamp` (rename only, same reasoning: reused by `reconciliation.py`'s pagination boundary check)
- `backend/config/settings.py` — added `WAHA_BASE_URL`, `WAHA_API_KEY`
- `backend/.env.example`, `infrastructure/office/.env.example` — added the same two variables
- `backend/requirements.txt` — added `requests==2.31.0` (already a transitive dependency in this environment; now an explicit direct one since the backend calls out to WAHA for the first time)
- `backend/apps/sync/tests.py` deleted, replaced by the `tests/` package above
- **Pagination round**: `backend/apps/sync/waha_client.py` (`offset` parameter added), `backend/apps/sync/reconciliation.py` (single-page fetch replaced with the bounded multi-page generator described in Section 5 — this is the one substantive algorithm change in this update), `backend/apps/sync/management/commands/reconcile.py` (`--max-pages` option added), `backend/apps/sync/tests/test_waha_client.py` and `test_reconciliation.py` (pagination tests added), `backend/apps/sync/tests/fixtures.py` (`make_message` helper added for synthetic paginated histories)

No frontend, BFF, authentication, blast, or unrelated model/infrastructure files were touched.

## 18. Database migrations

**None.** `makemigrations --check --dry-run` confirms no changes — `SyncCheckpoint` was used exactly as it already existed (Phase 2), with its `checkpoint_value` semantics now clarified by your decision (Section 10), not by a schema change. Pagination is entirely application-layer logic.

## 19. Known limitations

1. ~~Pagination beyond one page is not implemented~~ — **RESOLVED this
   round**: bounded multi-page pagination using confirmed `limit`+`offset`
   is now implemented (Section 5).
2. ~~Response envelope shape unconfirmed~~ — **RESOLVED this round**:
   confirmed bare JSON array (Section 6).
3. **Webhook HMAC auth still unverified** — unchanged; out of this
   phase's scope but still open overall.
4. **Outbound (`sendText`) live behavior and group-chat behavior remain
   unverified** — this round's evidence was read-only history queries,
   not a live send or a group message.
5. **Identity fragmentation** (same contact under two `Chat` identities)
   remains a known, accepted limitation, not fixed — per your explicit
   instruction not to invent a merge rule.
6. **Reconciliation only covers chats already known locally** — by
   design (Section 9), not a gap, but worth restating: a chat that has
   never appeared via webhook will never be discovered by this phase's
   reconciliation.
7. **The watermark stopping condition (Section 5, condition 2) assumes
   consistently newest-first ordering holds across all future queries** —
   confirmed for the queries checked this round; if a future WAHA update
   changed ordering, this stopping condition could stop too early. Not
   something to defend against speculatively, but worth knowing if
   reconciliation behavior ever looks incomplete after a WAHA upgrade.

## 20. Security considerations

- No secret was printed, logged, or committed at any point. `backend/.env`
  was read only by a script that set values directly into `os.environ`
  in-process — never echoed, never passed through a shell that could log
  it, never included in any test, fixture, or this report.
- `WahaClient` never includes the API key in a URL (header only) and
  never includes it in an error message — verified by
  `test_network_error_raises_waha_client_error_without_leaking_key` and
  `test_sends_api_key_header_not_query_param`.
- The PostgreSQL verification ran inside a rolled-back transaction
  specifically so no trace would be left in a real, apparently
  now-in-use development database.
- No table was truncated, no migration was reset, no existing row was
  read, modified, or deleted — only rows created by this verification
  itself (which were then rolled back) were touched.
- Two other `.env` files now exist in this repository
  (`bff/.env`, `frontend/.env`) that weren't present in earlier phases —
  noted for awareness only; not read, not touched, out of this phase's
  scope (frontend/BFF).

## 21. Whether Phase 5 is safe to start

**Not a blocking recommendation either way from this report alone** —
that determination depends on what Phase 5 (Celery/Redis, per
`docs/15-CODING-PHASES.md`) actually needs. What this phase can say
concretely: the reconciliation mechanism is implemented, tested (114/114
passing), and now has both genuine real-database confirmation and
genuine live-pagination confirmation behind it — the strongest evidentiary
foundation any phase in this project has had at its equivalent point.
The main things still worth resolving with real WAHA credentials before
reconciliation runs unattended in production: webhook HMAC auth
(unrelated to this phase, still open since Phase 3), and outbound/group
behavior (Section 19, items 3–4) — neither blocks Phase 5's own
implementation and testing, which can follow the same pattern used
successfully across Phases 3 and 4.

---

**Scope confirmation**: only Phase 4 was implemented. No frontend, BFF,
authentication, blast, mass messaging, or production deployment changes.
No Docker topology change. No new database. No migration reset. No
destructive database operation of any kind.
