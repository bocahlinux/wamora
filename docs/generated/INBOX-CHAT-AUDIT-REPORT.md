# Inbox/Chat (Canonical Phase 8) — Audit Report

**Read-only.** No source, config, `.env`, dependency, infrastructure, or
database file was modified. **No implementation was performed.**
Canonical Phase 9 was not started.

**What was inspected this task** (fresh reads, not relied on from
memory): `docs/15-CODING-PHASES.md`, `docs/00-MASTER-SPEC.md`,
`docs/02-REQUIREMENTS.md`, `docs/03-UI-UX-SPEC.md`, `docs/04-DATA-MODEL.md`,
`docs/05-WEBHOOK-SYNC-DESIGN.md`, `docs/06-SECURITY.md`,
`docs/07-API-CONTRACT.md`, `docs/09-TEST-PLAN.md`,
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`,
`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` Section 11,
`backend/apps/chats/models.py`, `backend/apps/chats/tests.py`,
`backend/apps/webhooks/services.py` + `parsing.py`,
`backend/apps/sync/reconciliation.py` + `waha_client.py`,
`backend/config/settings.py` (`REST_FRAMEWORK`), `bff/src/wahaAllowlist.ts`,
`bff/src/routes/messages.ts`, `frontend/src/pages/InboxPage.tsx`,
`frontend/src/components/ui/` (full directory listing), and a read-only
query of this environment's actual `Chat`/`Message`/`Contact` row counts.

---

## 1. Canonical Inbox/Chat requirements — exact text found

`docs/15-CODING-PHASES.md` itself gives only a one-line name: **"8.
Inbox/chat."** No elaboration lives in that file. The substance comes
from the documents it implicitly depends on:

- `docs/00-MASTER-SPEC.md` "Fitur": *"chat list; message history;
  receive/send/reply; mark as read."*
- `docs/02-REQUIREMENTS.md` "Functional": *"chats; messages; send/reply;
  mark read."*
- `docs/03-UI-UX-SPEC.md` "Screens": lists "Inbox" as one of five core
  screens, with no further detail beyond the global status
  requirements (which apply app-wide, not specifically to Inbox).
- `docs/07-API-CONTRACT.md`: lists **"chats, messages, send text, mark
  read"** as *"Frontend -> BFF"* examples, and separately lists
  *"durable conversation views"* as a *"Frontend -> Django"* example —
  **see Section 11 for why these two lines are in tension**, not simply
  additive.
- `docs/04-DATA-MODEL.md` "Message identity": stable provider/WAHA IDs
  scoped by session, never body/timestamp/sender alone (already fully
  implemented — Section 2).
- `wamora-design-assets/…/WAMORA-FRONTEND-DESIGN-SPEC.md` Section 11: a
  three-pane desktop layout (chat list / conversation / contact info),
  visually distinct sent/received messages, subtle timestamps, small
  delivery/read indicators, consistent attachment icons — a **visual**
  spec, not a functional one; it does not define data sources, pagination,
  or read-state semantics.

No document defines: pagination page size, whether search/filtering is
required (the design spec shows a "Search"/"Filters" box in the chat-list
pane, but as a visual element only — no functional doc names what fields
are searchable), or the precise semantics of "mark as read" (per-message?
per-chat? does it call WAHA to mark read on the phone too, or is it
purely a local UI/DB flag?).

---

## 2. Backend (Django) capabilities that already exist

- **Models — fully built, migrated, tested**: `Contact`, `Chat`,
  `Message`, `MediaReference` (`apps/chats/models.py`). Message identity
  is enforced at the DB level (`UniqueConstraint(session,
  provider_message_id)`), exactly matching the data-model doc's rule.
  `Chat` has `last_message_at` (indexed with `session`) — ready-made
  ordering key for a chat list. `Message` has `(chat, timestamp)`
  indexed — ready-made ordering key for a conversation's history.
- **Ingestion — fully built, tested, and this session directly
  re-confirmed the logic**: `apps/webhooks/services.py::persist_message()`
  is shared by both live webhook ingestion and reconciliation, so chat/
  contact/message records get created consistently by either path.
  `Chat.objects.get_or_create` happens automatically the first time any
  message for that chat is seen. **However**, `SUPPORTED_EVENT_TYPES =
  {'message'}` (`apps/webhooks/parsing.py`) — **only inbound/outbound
  message events are processed.** Any other WAHA webhook event (e.g. a
  read-receipt/`ack`-style event, if WAHA sends one) is stored as a raw
  `WebhookEvent` with status `unsupported` and never turned into durable
  state — directly relevant to "mark as read" (Section 6).
- **Reconciliation — fully built, tested, confirmed against real
  WAHA**: `apps/sync/reconciliation.py` fetches paginated message
  history per chat, duplicate-safe, checkpointed. **Important
  limitation, confirmed by reading the code, not assumed**: it only
  reconciles `Chat` rows that **already exist** in the DB
  (`chats = Chat.objects.filter(session=session)`) — it has no
  capability to discover a brand-new chat that has never had a single
  message delivered via a live webhook. `apps/sync/waha_client.py` only
  implements `fetch_chat_messages()` (per-chat history); there is no
  `list_chats`/"fetch all chats" method calling WAHA's own chat-list
  endpoint anywhere in this codebase.
- **No HTTP API of any kind exists for chats/messages.** `apps.chats`
  has no `urls.py`, no `views.py`, no `serializers.py` — confirmed by
  directory listing. Nothing in Django currently exposes this data over
  HTTP.
- **Reusable authentication pattern**: `apps.authn.authentication.
  JWTAuthentication` (built for the Dashboard endpoints, already
  verifies the same Django-issued JWT the BFF also verifies) is directly
  reusable for any new Django chat-read endpoints — no new auth
  mechanism would be needed.
- **No pagination configured project-wide**: `REST_FRAMEWORK` in
  `config/settings.py` has only `DEFAULT_RENDERER_CLASSES` and
  `EXCEPTION_HANDLER` — no `DEFAULT_PAGINATION_CLASS`. Every existing
  DRF view returns an unpaginated response (fine for the Dashboard's
  bounded aggregates; not fine for a chat list or message history,
  which the API contract's own stated principles say must be paginated).

**Actual current data in this environment** (read-only query, not
altered): **1** `Chat` row, **0** `Message` rows, **0** `Contact` rows.
Whatever created that one Chat row left it empty — there is essentially
no real conversation data to display yet in this local environment. This
doesn't block building the feature, but it does mean a first
implementation's "positive path" (a chat with real message history)
cannot currently be demonstrated end-to-end here without either live
WhatsApp traffic or a reconciliation run against a session with history.

## 3. BFF capabilities/endpoints that already exist

- **Send text — fully built, tested, idempotent**:
  `POST /api/sessions/:session/messages` (`bff/src/routes/messages.ts`),
  with the full `Idempotency-Key`/`OutboundOperation` state machine
  already audited in earlier reports. **Directly reusable as-is** for an
  Inbox composer — no BFF change needed for sending.
- **Everything else the contract doc names is not built.**
  `bff/src/wahaAllowlist.ts` (`WAHA_ALLOWED_ENDPOINTS`) — the
  *structural, code-enforced* allowlist this project's own hard rule
  requires (`docs/CLAUDE.md` rule 5: BFF must use an explicit allowlist,
  never a generic proxy) — contains exactly: `getSessionStatus`,
  `startSession`, `stopSession`, `restartSession`, `logoutSession`,
  `getQr`, `requestPairingCode`, `sendText`. **There is no
  `getChats`/`getChatMessages`/`markRead` entry, and no route file
  implementing any of them.** The API contract doc's own example list
  ("chats, messages, send text, mark read" under "Frontend -> BFF") is
  therefore only 1-of-4 implemented (send text) — the rest is
  documentation of an *intended* surface, not built.

## 4. Frontend components/hooks/routes that already exist and can be reused

- **`InboxPage.tsx`**: currently an honest `EmptyState` placeholder
  (`PlaceholderPage`), with its own comment already correctly citing
  "Phase 8" and the missing Django read API — consistent with this
  audit's own findings, not stale.
- **Directly reusable, confirmed by directory listing**: `Card`,
  `EmptyState`, `LoadingState`, `ErrorState`, `StatusBadge`,
  `PageHeader`, `Button`, `IconButton`, `Input`, `Badge`, `Modal` (built
  for Session Management — reusable for e.g. a contact-info drawer or a
  media-preview overlay), `ConfirmDialog`. `useApiQuery` (loading/
  success/error state machine, already used by every existing page).
  `frontend/src/lib/bffApi.ts`/`djangoApi.ts` establish the exact typed-
  client-function pattern any new endpoint wrapper would follow;
  `authHeader()` already handles the Bearer token uniformly.
- **Does not exist yet, confirmed absent**: `DataTable`, `Pagination`,
  `Tabs`, `SearchInput` (all named in the design spec's Section 8 core-
  component list, none built) — a paginated/searchable chat list and a
  scrolling message thread would need at least a list/pagination
  pattern; none currently exists anywhere in this codebase to reuse
  (the Dashboard's activity feed is a small, non-paginated, bounded
  `?limit=` list — not a reusable pagination component).
- **Session Management's own recent work is directly relevant
  precedent**: `SessionsPage.tsx`'s settlement-polling mechanism
  (`docs/generated/SESSION-MANAGEMENT-STATUS-SYNC-REPORT.md`) is the
  closest existing example of "keep something fresh without a page
  reload" in this codebase — relevant if Inbox ends up polling for new
  messages (Section 9).

## 5. Which required data sources already exist, which don't

| Data source | Exists? |
|---|---|
| Chat records (durable) | Yes — model + ingestion + reconciliation all functional |
| Message records (durable) | Yes — same |
| Contact records (durable) | Yes — same, though only populated from inbound non-group messages (Section 2 quote) |
| Media references | Model exists (`MediaReference`); **how the frontend would actually fetch/display the referenced media bytes is not defined anywhere** — `storage_reference` is a free-text field with no documented URL-serving mechanism. Not usable as-is without a product/design decision. |
| Read/unread state | **Does not exist** — no field on `Message` or `Chat`, no model in `docs/04-DATA-MODEL.md`'s own "Suggested entities" list either |
| Chat discovery for chats WAHA has but Django has never seen a message for | **Does not exist** — Section 2's reconciliation limitation |
| Send capability | Yes — BFF `sendText`, fully built |

## 6. Missing API endpoints

- Django: chat list (paginated, ordered by `last_message_at` desc),
  chat detail / message history for one chat (paginated, ordered by
  `timestamp`). Neither exists.
- Django or BFF (Section 11 decides which): a "mark as read" endpoint —
  doesn't exist, and its semantics aren't defined yet either (Section 9).
- BFF (only if the BFF-proxy direction is chosen — Section 11): `chats`/
  `messages` read passthroughs — don't exist, would need new
  `wahaAllowlist.ts` entries and new route files.
- Chat discovery: no endpoint anywhere (Django or BFF) that lists all of
  WAHA's chats for the configured session, independent of Django's
  already-known `Chat` rows.

## 7. Schema/migration changes required

- **For chat list + message history (read-only), as they exist
  today: none.** The current schema already supports it — a Django
  `ListAPIView`-style read over existing `Chat`/`Message` tables needs
  no new column or table.
- **For "mark as read": yes, a migration would be required** — no field
  exists to store it. Exactly what field(s)/table(s) depends on the
  semantics decision (Section 9), which this audit does not make.
- **For chat discovery (Section 2's gap)**: no schema change needed
  (uses the existing `Chat` table) — the gap is a missing WAHA-client
  method + sync logic, not a data-model gap.

## 8. Authentication/authorization requirements

- **Reuse, don't invent**: `apps.authn.authentication.JWTAuthentication`
  + `IsAuthenticated`, the exact pattern the Dashboard endpoints already
  use, is directly applicable to any new Django chat-read endpoint — no
  new mechanism needed.
- **No fine-grained authorization model exists anywhere in this
  project** (confirmed again this task, consistent with every prior
  audit's finding) — any authenticated user sees all data. For
  aggregate dashboard numbers this was an accepted, documented posture;
  for **message content** specifically, this deserves a fresh look as a
  product decision (does every authenticated operator need to read
  every conversation's full text?) rather than silently inheriting the
  same posture — this audit surfaces the question, it does not answer
  it.
- If the BFF-proxy direction is chosen for reads (Section 11), the
  existing `requireAuth`/`requireScope('reading')` pattern
  (`bff/src/middleware/auth.ts`) is directly reusable there too — the
  `reading` scope already exists in `JWT_SCOPES` and is already used by
  the session-status route.

## 9. Pagination, ordering, search, filtering, unread state, message history, conversation relationships

- **Pagination**: required by the API contract's own stated principles,
  and practically necessary (message history can be arbitrarily long) —
  **not configured anywhere in Django today** (Section 2). Would need a
  `DEFAULT_PAGINATION_CLASS` (or explicit per-view pagination) added.
- **Ordering**: chat list — `last_message_at` descending, already
  indexed. Message history — `timestamp` ascending or descending
  (product choice: chat UIs conventionally show oldest-at-top,
  newest-at-bottom, with pagination loading older messages on scroll-up
  — not specified by any doc here), already indexed via `(chat,
  timestamp)`.
- **Search/filtering**: shown as a visual element in the design spec's
  reference layout only — **no functional document specifies what's
  searchable** (contact name? message body? both?). A genuine open
  product question, not an engineering gap.
- **Unread state**: does not exist (Section 5/6).
- **Message history**: exists and is reconciled/ingested correctly;
  simply has no read API yet.
- **Conversation/session relationships**: `Chat` belongs to exactly one
  `WahaSession` and optionally one `Contact`; `Message` belongs to one
  `Chat` and one `WahaSession`. Consistent with, and does not conflict
  with, this project's current single-session scope.
- **Real-time delivery — explicitly unresolved anywhere in this
  project**: `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s own "Open"
  list names **"WebSocket vs SSE"** as an undecided question. This is
  directly relevant to Inbox/Chat (new incoming messages arriving while
  the page is open) and is the single most significant **product/
  architecture decision** this audit found still outstanding. Until
  it's resolved, the only currently-supported mechanism for "new
  message appeared" is the same polling pattern already used by
  Dashboard/Sessions in this codebase — functional, but explicitly a
  fallback, not a decided design.

## 10. Dependencies/blockers caused by WAHA/session architecture

- The BFF is single-session by construction (`WAHA_SESSION_NAME`,
  already documented extensively in the Session Management reports) —
  Inbox/Chat for **the one configured session** is unaffected by this;
  it only becomes a blocker for a *multi-session* inbox, which is
  explicitly not this project's current documented scope
  (`docs/00-MASTER-SPEC.md`: "Awal: 1 session").
- Sending is already proven to work end-to-end against real WAHA
  (`sendText`, tested and — per the Session Management reports — already
  live-verified for auth/routing against the real running BFF this
  session, though not against a real WhatsApp send).
- Reading message history from WAHA directly (as opposed to from
  Django's durable copy) is proven to work
  (`apps/sync/waha_client.py::fetch_chat_messages`, confirmed against
  the real deployed WAHA instance per its own docstring) — this
  capability exists in Django's reconciliation code today but is not
  exposed over HTTP to anything.
- No blocker was found that would prevent building a single-session
  Inbox against Django's already-populated durable tables.

## 11. Conflicts between the canonical spec and the existing implementation

**The one real conflict found**: `docs/07-API-CONTRACT.md` lists
"chats, messages, send text, mark read" under **"Frontend -> BFF"**,
while `docs/00-MASTER-SPEC.md` states PostgreSQL (Django-owned) holds
"durable... chats/messages..." and the **already-built Dashboard
precedent** (Phase 8 dashboard work) established a **Frontend ->
Django direct** pattern specifically for durable reads
(`/api/dashboard/messages/`, `/api/dashboard/activity/` — both go
straight to Django, not through the BFF). For a chat list / message
history **read**, these two documented directions disagree:
- Reading "the contract doc's own words" literally → BFF should proxy
  chat/message reads (would require new BFF endpoints and, per
  `docs/CLAUDE.md` rule 5, new explicit `wahaAllowlist.ts` entries even
  though the data being read is Django's durable copy, not a live WAHA
  call — an odd fit, since the BFF has no reason to call WAHA at all for
  data Django already owns).
- Reading "who owns the data" (`00-MASTER-SPEC.md`) and "the pattern
  already chosen and built for durable reads" (Dashboard) → Frontend
  should call Django directly for chat/message reads, exactly like it
  already does for messages-today/activity, and the BFF stays focused on
  live WAHA session control + sending (its already-established role).

**This audit does not resolve this itself** — it is a genuine,
documented ambiguity between two source-of-truth documents, and silently
picking one would be exactly the kind of unstated architectural decision
this task was told not to make. It is the single highest-priority open
question before any Inbox/Chat implementation begins (Section 13, Step
0).

No other conflict was found — everything else (models, message
identity, webhook idempotency, JWT reuse) is consistent between the
documented spec and what's already built.

## 12. MUST HAVE / NICE TO HAVE / NOT READY

**MUST HAVE** (a minimal, honest Inbox v1, assuming Section 11 is
resolved in favor of Frontend → Django direct reads, matching the
Dashboard precedent):
- A `DEFAULT_PAGINATION_CLASS` added to Django's `REST_FRAMEWORK`
  settings (or explicit per-view pagination).
- `GET /api/chats/` — paginated chat list, `JWTAuthentication` +
  `IsAuthenticated`, ordered by `last_message_at` desc.
- `GET /api/chats/:id/messages/` — paginated message history for one
  chat, same auth pattern, ordered by `timestamp`.
- Frontend: a chat-list pane and a conversation pane, wired to the two
  endpoints above, reusing `useApiQuery`/`Card`/`LoadingState`/
  `ErrorState`/`EmptyState` exactly as every existing page does.
- Frontend: a composer wired to the **already-built** BFF `sendText`
  endpoint — no backend/BFF work needed for this specific piece.

**NICE TO HAVE**:
- A contact-info pane/drawer (third column) using `Contact`'s existing
  `display_name`/`phone_number` fields — straightforward once the main
  two panes exist; could reuse the `Modal`/drawer pattern from Session
  Management.
- Search/filter in the chat list — blocked on a product decision (which
  fields), not an engineering blocker once decided.
- Media display — blocked on defining how `MediaReference.
  storage_reference` actually becomes a servable URL; not currently
  specified anywhere.

**NOT READY**:
- "Mark as read" — no data model, no semantics decision, needs a
  migration once decided (Section 7/9).
- Chat discovery for chats Django has never received a webhook for —
  needs a new WAHA-client capability (`list_chats`) and a decision on
  whether/how it runs (Section 2/6).
- Real-time new-message delivery — explicitly an open architectural
  decision (`WebSocket vs SSE`, Section 9) with no fallback specified
  beyond this project's existing polling pattern.
- The BFF-vs-Django read-path question itself (Section 11) — blocks
  committing to either endpoint location with confidence.

## 13. Concrete implementation sequence (NOT executed — for future approval)

0. **Resolve Section 11's BFF-vs-Django read-path decision.** Everything
   below assumes the Django-direct answer, since it requires no new BFF
   allowlist entries and directly matches the already-built Dashboard
   precedent — but this is a recommendation for you to confirm, not a
   decision already made.
1. Add DRF pagination configuration to `backend/config/settings.py`.
2. Add `apps/chats/serializers.py` + `views.py` + `urls.py`: `GET
   /api/chats/` (list, paginated, `JWTAuthentication`).
3. Add `GET /api/chats/:id/messages/` (paginated message history),
   same app, same auth pattern.
4. Wire `config/urls.py`'s `path('api/chats/', include(...))`.
5. Frontend: `frontend/src/lib/djangoApi.ts` additions (`getChats()`,
   `getChatMessages(chatId, page)`), following the existing typed-client
   pattern exactly.
6. Frontend: chat-list pane component, reusing `Card`/`LoadingState`/
   `ErrorState`/`EmptyState`.
7. Frontend: conversation/message-thread pane component.
8. Frontend: composer, wired to the **existing, unmodified** BFF
   `sendText` client function (already built for Session Management's
   messages.ts contract — no new BFF work).
9. Replace `InboxPage.tsx`'s placeholder with the assembled three-part
   (or two-part, pending the contact-info decision) layout.
10. *(Deferred, needs decisions first)*: mark-as-read, chat discovery,
    search/filter, real-time delivery — each independently schedulable
    once its respective open question (Sections 7, 9, 2) is answered.

Each numbered step above is independently small and testable, matching
this project's established phase-by-phase discipline — presented here
as a sequence for your approval, not as work already done.

---

This was a read-only audit. No implementation was performed. Not
proceeding to Inbox/Chat implementation or canonical Phase 9
automatically.
