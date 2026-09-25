# Phase 9.1B — Webhook Timestamp — Design Audit Report

**This is a read-only design audit. No source, config, test, migration,
dependency, or documentation file was modified. No container was
started, stopped, or restarted. No WAHA/Celery/database write occurred.**

**Conclusion up front:** Phase 9.1B is a small, backend-only,
non-breaking addition — one new field (`last_webhook_received_at`) on
the already-existing `GET /api/sync/status/<session_name>/` response
(built in Phase 9.1A), computed from the already-existing
`WebhookEvent.received_at` column via one additional aggregate query.
**No migration, no BFF change, no required frontend change.** The one
genuine open question is not architectural but a **product decision
already flagged, and still unresolved, in the original Phase 9.1 design
audit: whether this field is wanted at all** — see Section 16.

---

## 1. Objective

Determine exactly what remains to implement Phase 9.1B — Webhook
Timestamp — by tracing the real, current webhook/sync-status code paths
end to end, without assuming any prior report's description is still
accurate.

---

## 2. Official Roadmap Requirement

**VERIFIED FROM SOURCE.** `docs/15-CODING-PHASES.md` (the canonical
phase list referenced by `docs/CLAUDE.md`) contains **no mention of
"9.1" phases at all** — confirmed via a direct search
(`grep -in "9\.1" docs/15-CODING-PHASES.md` → no matches). The entire
Phase 9.1A/9.1B/9.1C/... numbering is a construct introduced by this
session's own generated design-audit reports
(`docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`), not part of the
original spec set (`docs/00`–`docs/15`). This is stated plainly, not to
question the phase's legitimacy, but because "the official roadmap
requirement" for 9.1B is only findable in `docs/generated/`, not
`docs/`.

**The definition, quoted from `docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`:**

> **9.1B — Backend: `last_webhook_received_at` addition** (Section 6.A).
> Naturally extends 9.1A's same response if built together, but is
> logically independent — a separate query, no shared state with the
> checkpoint logic.

And, from that same report's Section 6.A (API Design Proposal):

> `last_webhook_received_at` — one additional query
> (`WebhookEvent.objects.filter(session=session).aggregate(Max('received_at'))`),
> optional but cheap, directly serving Section 4/gap 6's partial
> mitigation.

And Section 4, gap 6:

> No way to distinguish "webhook stopped arriving" from "WhatsApp is
> quiet" — architecturally unsolvable with currently-available data,
> not merely unbuilt.

**Extracted expectations:**
- **Expected behavior**: add one field to the existing sync-status
  response reporting the most recent time *any* webhook was received
  for that session (independent of whether reconciliation ever ran).
- **Expected data source**: `WebhookEvent.received_at` (already exists,
  Phase 3), aggregated with `Max()` per session.
- **Expected consumer**: `GET /api/sync/status/<session_name>/`
  (`apps.sync.views.SyncStatusView`, built in 9.1A) — no new endpoint.
- **Expected UI/API effect**: explicitly labeled "**Backend**" in the
  dependency-order list (Section 2 above) — the roadmap source does
  **not** specify a required frontend change. The report's own Section
  4/gap 6 language ("partial mitigation") signals this is an
  operator-facing raw signal, not a fully-solved UX feature — it
  explicitly does **not** claim to solve gap 6 (distinguishing "webhook
  stopped" from "WhatsApp is quiet"), only to make the underlying data
  available.

**INFERRED, not verified**: no document states a target frontend
location for this field (unlike Phase 9.1A/9.1D/9.1E's `sync_status`
badge and Phase 9.1F's Redis card, both of which had an explicit UI
proposal in the same reports). This absence is itself a finding, not an
oversight on this audit's part — see Section 9.

---

## 3. Current Webhook Flow — Traced End to End

**VERIFIED FROM SOURCE** (every file below was read directly this
session, not inferred from a prior report):

```
WAHA
  → POST (WahaWebhookView, backend/apps/webhooks/views.py)
      - HMAC signature check (authentication.py)
      - parse_envelope() (parsing.py) — event/session/payload.id
  → ingest_webhook() (services.py)
      - WahaSession.objects.get_or_create(name=envelope.session_name)
      - WebhookEvent.objects.get_or_create(session, provider_event_id,
          defaults={event_type, payload})   <-- received_at set HERE,
                                                 auto_now_add=True
      - if event_type == 'message':
          parse_message() (parsing.py) → ParsedMessage.timestamp
              (parsed from payload['timestamp'], a WAHA-supplied Unix
              epoch number — SOURCE EVENT TIME)
          persist_message() → Message.objects.create(..., timestamp=parsed.timestamp)
              (apps/chats/models.py — a PER-MESSAGE field, unrelated to
              WebhookEvent)
      - webhook_event.status/processed_at updated, received_at NEVER
        touched again after creation
  → response {"status": "ok", "webhook_event_id": ..., "processing_status": ...}
```

No BFF involvement anywhere in this inbound path — WAHA calls Django
directly (matches `docs/CLAUDE.md`'s architecture; the BFF only mediates
outbound Frontend→WAHA calls).

---

## 4. Timestamp Source — Two Distinct, Already-Separated Timestamps

**VERIFIED FROM SOURCE.** This codebase already cleanly separates the
two kinds of time the audit's Step 3 asked to distinguish:

| | **`WebhookEvent.received_at`** | **`Message.timestamp`** |
|---|---|---|
| Meaning | **SERVER RECEIVED TIME** — when Django's `get_or_create()` first inserted this webhook delivery's row | **SOURCE EVENT TIME** — WAHA's own reported message timestamp |
| How set | `models.DateTimeField(auto_now_add=True)` (`apps/webhooks/models.py:40`) — Django/DB clock, not from the payload | `parse_timestamp(payload.get('timestamp'))` (`apps/webhooks/parsing.py:185-193`) — parsed from the WAHA payload's own `timestamp` field |
| Scope | Per webhook delivery (one row per `(session, provider_event_id)`) | Per message (one row per `(session, provider_message_id)`) |
| Used by 9.1B? | **Yes — this is exactly what `last_webhook_received_at` (Section 2) aggregates.** | No — unrelated to this phase |

**Phase 9.1B's `last_webhook_received_at` is unambiguously the SERVER
RECEIVED TIME signal**, not the source event time — this matches its
purpose (Section 4/gap 6: "is WAHA still delivering to us," a
connectivity/liveness question, not a message-content question).

---

## 5. Timestamp Format

**VERIFIED FROM SOURCE.**

- WAHA supplies `payload['timestamp']` as a Unix epoch number (int or
  float) — `parse_timestamp()` converts via
  `datetime.datetime.fromtimestamp(raw, tz=datetime.timezone.utc)`, with
  a fallback to `timezone.now()` (server time) if the value is missing
  or not numeric (`parsing.py:185-193`, module docstring flags this
  fallback as "not the true WhatsApp message time"). **This fallback
  path is irrelevant to 9.1B** — it feeds `Message.timestamp`, not
  `WebhookEvent.received_at`.
- `WebhookEvent.received_at` has **no such ambiguity**: it is always
  `auto_now_add=True`, i.e. always the Django server's own clock at
  INSERT time, in UTC (`settings.py`'s `TIME_ZONE='UTC'`,
  `USE_TZ=True` — project-wide convention, unchanged, reused by every
  other timestamp field in this codebase).
- Existing serialization precedent (`apps/sync/views.py:_isoformat()`,
  already used by `last_run_at`/`checkpoint_updated_at` in the very
  response 9.1B extends): manual ISO-8601 with a literal trailing `Z`
  instead of `+00:00`. Any 9.1B implementation should reuse this exact
  helper, not invent a second formatting convention in the same
  response body.

---

## 6. Persistence Analysis — No Schema Change Required

**VERIFIED FROM SOURCE.**

- `WebhookEvent.received_at` already exists as a column, present since
  the app's very first migration (`apps/webhooks/migrations/0001_initial.py:25`,
  confirmed by direct read) — not touched by the later
  `0002_alter_webhookevent_status.py`.
- `last_webhook_received_at` is a **derived, computed-on-read value**
  (`Max('received_at')` per session), not a new column on any model.
  **No new migration is required or proposed** — consistent with the
  original design report's own framing ("one additional query," never
  "one additional field on the model").
- `apps/sync/migrations/` currently has only `0001_initial.py`
  (`SyncCheckpoint`) — 9.1B does not touch `SyncCheckpoint` at all; the
  aggregate query targets `WebhookEvent`, a different app's model,
  queried directly from `apps.sync.views`, mirroring the pattern
  `apps.dashboard.views.ActivityFeedView` already uses to read
  `WebhookEvent` from outside its own app.
- **Per Step 4's explicit instruction**: since no schema change is
  needed, there is nothing to "stop the implementation recommendation
  at the design level" for — this section is included for completeness,
  not because a schema change was found.

---

## 7. Backend API Analysis

**VERIFIED FROM SOURCE**, current exact response shape of
`GET /api/sync/status/<session_name>/` (`apps/sync/views.py:129-136`):

```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:05Z"
}
```

**No `last_webhook_received_at` field exists yet** — this confirms
9.1B is genuinely not yet implemented (not merely undocumented).

Classification against Step 5's options:
- **(B) — backend has the data but does not expose it.** The data
  (`WebhookEvent.received_at`) already exists and is already queried
  elsewhere (`ActivityFeedView`, Section 3 above) — this view simply
  does not yet perform the per-session `Max()` aggregate or include it
  in the response dict.

**A pre-existing test would need updating, not just extending** — found
during this audit, worth flagging explicitly since Step 11 asks for
files that "must change":
`backend/apps/sync/tests/test_views.py::SyncStatusViewTests::test_query_count_is_bounded_no_n_plus_one`
(lines 218-231) currently asserts **exactly 2** domain queries per
request (`WahaSession` lookup + `SyncCheckpoint` lookup). Adding the
`WebhookEvent` aggregate is a **third** query — this test's hardcoded
`assertEqual(len(domain_queries), 2)` would need to become `3`, and its
`domain_queries` filter (currently matching only
`waha_sessions_wahasession`/`sync_synccheckpoint` table names) would
need a third table-name match added
(`webhooks_webhookevent`) or the aggregate's row simply wouldn't be
counted and the test would pass for the wrong reason — this must be
handled deliberately, not incidentally, at implementation time.

---

## 8. BFF Analysis

**VERIFIED FROM SOURCE — zero involvement.** `bff/src/routes/messages.ts`
and `bff/src/djangoClient.ts` contain the only two hits anywhere in
`bff/src` for the string "webhook", and both are an unrelated comment
about WAHA not firing a webhook for self-sent messages (line 126/151) —
no route, DTO, or proxy logic touches `WebhookEvent`, webhook
timestamps, or `apps.sync`'s endpoint at all. This matches the
already-established Frontend→Django-direct pattern this endpoint uses
(`apps/sync/views.py`'s own module docstring: "the same Frontend ->
Django direct pattern apps.chats/apps.dashboard already use, not a new
BFF hop"). **BFF requires no change for 9.1B, and none is proposed.**

---

## 9. Frontend Analysis

**VERIFIED FROM SOURCE.**

- `frontend/src/lib/djangoApi.ts:166-173` — the `SyncStatus` interface
  currently has exactly the five fields the backend returns today
  (`session, sync_status, checkpoint_status, last_run_at,
  seconds_since_last_run, checkpoint_updated_at`) — no
  `last_webhook_received_at` field exists.
- `frontend/src/pages/InboxPage.tsx` (Phase 9.1E, re-confirmed this
  audit) — the **only** UI use of `SyncStatus` is a single
  `<StatusBadge status={mapSyncStatus(syncStatus.sync_status)}
  label={SYNC_STATUS_LABEL[syncStatus.sync_status]} />` next to the page
  title (line 312). **`last_run_at` and `checkpoint_updated_at` — two
  timestamp fields already present in today's API response — are
  fetched into `syncStatus` state but are never rendered anywhere in
  the UI.** This is a directly relevant, pre-existing precedent: adding
  `last_webhook_received_at` to the same response would, by default,
  land in exactly the same "available but unused" position as those two
  fields already occupy — not a new gap 9.1B introduces, but the
  existing norm for this endpoint's timestamp fields.
- **Conclusion**: per Step 5/Section 2's "Backend:"-only scoping in the
  roadmap source, and given the frontend already carries two unused
  timestamp fields from this same endpoint with no complaint or
  follow-up task filed, **no frontend file change is required to
  satisfy Phase 9.1B as scoped**. Surfacing it visually (e.g. "last
  webhook: 3m ago" near the sync badge) would be a **separate,
  unscoped future enhancement**, not part of 9.1B's own definition —
  named here as a natural next question, not assumed as part of this
  phase.

---

## 10. Testing Analysis

**VERIFIED FROM SOURCE.** No test framework changes are implicated:

- Backend: `SyncStatusViewTests` (`apps/sync/tests/test_views.py`,
  Django `APITestCase`, already exercises this exact view) is the
  correct home for new 9.1B tests — no new test file needed, no new
  test framework.
- Frontend: confirmed (again) that no test framework exists in this
  project (`frontend/package.json` scripts: `dev`/`build`/`lint`/`preview`
  only) — irrelevant here anyway since Section 9 concludes no frontend
  change is required.

**Minimum tests recommended for implementation time** (not written now):
1. `last_webhook_received_at` is `null` when the session has zero
   `WebhookEvent` rows (mirrors the existing `never_synced`-style null
   handling already tested for the other fields).
2. `last_webhook_received_at` reflects the **most recent** of multiple
   `WebhookEvent` rows for the session (proves `Max()`, not `first()`/
   creation-order, is actually being used).
3. `last_webhook_received_at` is scoped **per session** — a
   `WebhookEvent` belonging to a *different* `WahaSession` must not
   leak into this session's aggregate (directly guards the
   `docs/CLAUDE.md`-adjacent principle of not mixing session data).
4. Format assertion matching `test_last_run_at_is_timezone_aware_utc_iso8601`'s
   existing pattern (`.endswith('Z')`).
5. `last_webhook_received_at` is independent of `sync_status`/checkpoint
   state — e.g. present and non-null even when `sync_status` is
   `'never_synced'` (no `SyncCheckpoint` row at all), since webhook
   ingestion and reconciliation are two separate pipelines (Section 3).
6. Update (not just re-verify) `test_query_count_is_bounded_no_n_plus_one`
   per Section 7's finding — assert **3** domain queries, with the
   third one matching the `WebhookEvent` table.

---

## 11. Security / Data-Integrity Analysis

**VERIFIED FROM SOURCE / reasoned from existing code, per Step 9:**

- **Authentication/authorization**: no change — reuses
  `SyncStatusView`'s existing `JWTAuthentication` +
  `IsAuthenticated`-only gate (no scope requirement), exactly as
  `last_run_at`/`checkpoint_updated_at` already are. No new
  authorization surface is introduced.
- **Sensitive-data exposure**: none. A bare UTC datetime carries no PII,
  no message content, and no raw error text — consistent with this
  endpoint's existing, deliberate exclusion of `SyncCheckpoint.last_error`
  (Section 6 of the original design report, re-confirmed unchanged in
  the current `views.py`).
- **Timezone ambiguity**: none — UTC end-to-end, same `_isoformat()`
  helper as the rest of this response (Section 5).
- **Inclusion scope worth naming explicitly**: the proposed
  `Max('received_at')` query is **not** filtered by `WebhookEvent.status`
  — a `pending`, `failed`, or `unsupported` webhook delivery still
  updates `received_at` on creation and would still count toward "last
  webhook received." This is the **correct** semantic for this field's
  stated purpose (Section 4/gap 6 — "is WAHA still delivering to us,"
  a connectivity signal, not a "did we successfully process it" signal)
  and matches `ActivityFeedView`'s existing precedent of listing
  `WebhookEvent` rows unfiltered by status — but it is a real behavioral
  choice worth stating plainly rather than leaving implicit, since a
  reader could otherwise assume only successfully-processed events
  count.
- **Event ordering / idempotency**: not implicated — this is a pure,
  read-only aggregate over already-idempotently-stored rows (the
  `(session, provider_event_id)` unique constraint, unchanged,
  guarantees no double-counting of a redelivered webhook regardless of
  how many times WAHA retries it).
- **Performance**: `WebhookEvent.received_at` is **not indexed**
  (`Meta.indexes` only covers `status` — confirmed directly in
  `models.py:51-53`); the aggregate is filtered by `session`
  (ForeignKey — implicitly indexed) first, then `Max()`s the matching
  rows, so the unindexed sort is bounded to one session's row count,
  not the full table — the same acceptable-for-now judgment
  `ActivityFeedView`'s own docstring already makes for a structurally
  identical query (Section 3 quote above: "flagged as a candidate
  `Index(fields=['received_at'])` if this becomes a hot path, not added
  speculatively here"). Not over-engineered further here, per Step 9's
  explicit instruction.

---

## 12. Files That Would Change (Minimum Implementation Plan)

**Not implemented in this task.** Per Step 11's format:

### `backend/apps/sync/views.py`
→ **Reason**: the only file that currently constructs the sync-status
response body; this is where the new field must be added.
→ **Approximate change**: import `Max` from `django.db.models` and
`WebhookEvent` from `apps.webhooks.models`; inside `SyncStatusView.get()`,
after the existing `checkpoint` lookup, add one line:
`last_webhook_at = WebhookEvent.objects.filter(session=session).aggregate(Max('received_at'))['received_at__max']`,
then add `'last_webhook_received_at': _isoformat(last_webhook_at)` to
the returned `Response({...})` dict, reusing the existing `_isoformat()`
helper already defined in this same file.
→ **Why no other backend file needs changing**: no new URL (existing
route, `apps/sync/api_urls.py`, is unchanged), no new model field
(Section 6), no new auth class (Section 11), no BFF file (Section 8).

### `backend/apps/sync/tests/test_views.py`
→ **Reason**: covers the exact view being changed; the existing
`test_query_count_is_bounded_no_n_plus_one` test would start failing
(2 → 3 queries) the moment the view change lands, so it must be updated
in the same change, not left to break.
→ **Approximate change**: update the query-count assertion (Section 7);
add the tests listed in Section 10.
→ **Why no other test file needs changing**: no other view, serializer,
or model changes; `apps/webhooks/tests/*` already cover
`WebhookEvent.received_at`'s own creation behavior and need no change
since that field itself is untouched.

**No other file** (no BFF file, no frontend file, no Docker/Compose
file, no `.env` file, no dependency file, no migration file) meets the
"must change" bar for Phase 9.1B as scoped — reasons given in Sections
6, 8, and 9 respectively.

---

## 13. Files Intentionally Not Changed

- `backend/apps/webhooks/models.py` — `WebhookEvent.received_at` already
  exists exactly as needed; no reason to touch it.
- `backend/apps/sync/models.py` (`SyncCheckpoint`) — 9.1B is explicitly
  independent of checkpoint state (Section 2's own "no shared state
  with the checkpoint logic").
- `backend/apps/sync/api_urls.py` / `urls.py` — route unchanged.
- Any file under `bff/` — Section 8.
- Any file under `frontend/` — Section 9 (no frontend change required
  by 9.1B's own scope; a future display enhancement is a separate,
  unscoped task).
- Any Docker/Compose/`.env` file — no new config surface.
- `backend/apps/dashboard/views.py` — its own, separate
  `WebhookEvent.received_at` usage (`ActivityFeedView`) is a different
  feature (recent-activity feed) and needs no change for 9.1B.

---

## 14. Minimum Implementation Plan

Already given in full, per-file, in Section 12 — not repeated here.
Total surface: **one production file, one test file, zero new
dependencies, zero migrations.**

---

## 15. Verification Plan

**VERIFIED DURING THIS AUDIT:**
- `WebhookEvent.received_at` exists as a real, migrated column
  (`0001_initial.py`), unindexed except implicitly via its `session_id`
  FK (Section 6/11).
- The current `SyncStatusView` response genuinely lacks
  `last_webhook_received_at` (Section 7, direct read of `views.py`).
- The frontend's `SyncStatus` interface and its only consumer
  (`InboxPage.tsx`) already tolerate — and already contain — unused
  timestamp fields from this same endpoint (Section 9).
- BFF has zero code touching this path (Section 8, direct grep of
  `bff/src`).
- `docs/15-CODING-PHASES.md` contains no "9.1" phase text at all
  (Section 2).

**TO BE VERIFIED DURING IMPLEMENTATION:**
- `manage.py test apps.sync` passes after the view change, including
  the updated query-count test and the new tests listed in Section 10.
- `manage.py check` / a full test-suite run shows no regression in
  `apps.dashboard`'s `ActivityFeedView` tests (unchanged file, but
  worth a sanity re-run since both views now read `WebhookEvent`).
- Live confirmation (curl or Django admin/shell) that
  `last_webhook_received_at` reflects a real, recent `WebhookEvent` for
  a session that has actually received live WAHA traffic — the dev
  stack's Office-side services were not running during this audit
  (confirmed via `docker ps` in the immediately preceding task this
  session), so this could not be checked live here.
- Confirm no other consumer of `GET /api/sync/status/` (none found in
  this codebase beyond `InboxPage.tsx`, but worth a final grep at
  implementation time) breaks on an additive JSON field — additive
  fields are non-breaking for any reasonable JSON consumer, but this is
  a "confirm," not an assumption, given `docs/CLAUDE.md` rule 8 ("never
  silently change the API contract").

**NOT VERIFIABLE WITHOUT EXTERNAL DEPENDENCY:**
- The real production/office environment's actual `WebhookEvent` volume
  and whether an unindexed `Max()` aggregate is truly cheap at that
  scale — this audit only confirms the query is *structurally* bounded
  per-session (Section 11), not its real-world latency, which needs a
  live database with production-representative data.
- Whether WAHA in this project's real deployment ever sends a webhook
  event whose `payload.id` collides in a way that defeats the
  `(session, provider_event_id)` uniqueness assumption underlying
  "no double counting" — unchanged, pre-existing assumption, not newly
  introduced or newly verifiable by this audit.

---

## 16. USER DECISIONS REQUIRED

**One item, carried forward, not newly introduced by this audit:**

1. **Whether `last_webhook_received_at` is wanted at all.** This exact
   question was already raised and left explicitly unresolved in
   `docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`, Section 12, item 6:
   *"Whether `last_webhook_received_at` (9.1B) is wanted at all — cheap,
   but adds one more field to the schema and one more query; not
   assumed."* This audit did not find any later report or message in
   which the user explicitly confirmed "yes, build it" — only that 9.1B
   next appears as an item in the dependency-ordered roadmap list. Since
   this task's own instructions are audit-only and explicitly forbid
   inferring intent beyond the source, this is surfaced as a genuine
   open decision rather than assumed resolved by virtue of being asked
   about.

**Not escalated (preference-level, per Step 10's own threshold):**
- Whether to add `Index(fields=['received_at'])` proactively — a
  reversible, low-stakes performance tuning choice (Section 11),
  identical in kind to the same open item `ActivityFeedView` already
  carries unaddressed.
- Exact field name/casing (`last_webhook_received_at`) — already fixed
  by the original design proposal; no ambiguity found.
- Whether/where a future frontend display would go — explicitly
  out-of-scope for 9.1B itself (Section 9), not a blocking decision for
  this backend-only phase.

**No architectural decision was found** (no new service, no new
database boundary, no new external dependency, no new API architecture,
no change to webhook ownership, persistence semantics, production
topology, or security behavior) — Step 10's escalation criteria are not
triggered by anything found in this audit.

---

## 17. Known Limitations

- This audit could not perform any live verification (Section 15) — the
  Office-side dev stack (Django/Celery/Redis) was confirmed not running
  immediately before this task (via `docker ps` in the prior task this
  session), and this audit did not start it, per the strict read-only
  scope.
- The roadmap's own source for "9.1B" lives only in a generated report,
  not the canonical `docs/` spec set (Section 2) — this audit treats
  that generated report as authoritative for *scope*, since it is the
  only document defining this phase at all, but flags the provenance
  difference for transparency.
- This audit did not attempt to determine real-world WAHA webhook
  volume/frequency for the configured session — the "cheap query"
  characterization (Section 11) is structural/relative, not a measured
  benchmark.

---

## 18. Final Recommendation

Phase 9.1B is a **small, low-risk, backend-only, additive** change: one
new response field on an existing endpoint, computed from an
already-existing, already-migrated column, via one already-precedented
query pattern (`ActivityFeedView` already reads `WebhookEvent` the same
way). No migration, no BFF change, and no frontend change are required
by the phase's own stated scope. The only pre-existing test this change
would break (`test_query_count_is_bounded_no_n_plus_one`) is identified
in advance (Section 7), so it can be updated deliberately rather than
discovered as a surprise failure.

**The sole blocker to starting implementation is not technical**: it is
the still-open product question, raised in the original design audit
and never since resolved in this session's visible history, of whether
this field is wanted at all (Section 16). Recommend confirming that
before implementing.

**STOP.** This was a design audit only. No implementation was
performed. Awaiting the user's decision on Section 16 before any further
action on Phase 9.1B.
