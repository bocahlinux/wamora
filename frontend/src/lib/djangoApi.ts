import { authHeader } from './auth';
import { config } from './config';
import { request, type ApiResult } from './api';

export interface ComponentHealth {
  status: string;
  component: string;
}

/** GET /api/health/ — backend process liveness (apps/core/views.py
 * LivenessView), deliberately independent of the database check below
 * (docs/01-ARCHITECTURE.md "Failure isolation"). No auth required. */
export function getBackendHealth() {
  return request<ComponentHealth>(`${config.djangoBaseUrl}/api/health/`);
}

/** GET /api/health/database/ — PostgreSQL reachability, independent of
 * backend liveness. No auth required. */
export function getDatabaseHealth() {
  return request<ComponentHealth>(`${config.djangoBaseUrl}/api/health/database/`);
}

/** GET /api/health/redis/ — Celery broker Redis reachability
 * (apps/core/views.py RedisHealthView, Phase 9.1C), independent of
 * backend/database liveness. Says nothing about Celery worker
 * liveness. No auth required. */
export function getRedisHealth() {
  return request<ComponentHealth>(`${config.djangoBaseUrl}/api/health/redis/`);
}

/** The Role merge — `Role` used to be a separate, purely scope/menu-
 * access concept (`custom_role`) alongside a fixed
 * `'global_admin'/'office_admin'/'operator'` string enum
 * (`OfficeMembership.role`). Both are now the same object: `scopes`
 * decides feature/menu access (JWT scopes), and
 * `grants_global_access`/`is_office_admin`/`is_operator` decide
 * organizational standing (global vs Office-scoped, administrative
 * authority, operator/assignment eligibility) — independent booleans,
 * not a re-creation of the old enum, since a Superadmin-defined Role can
 * combine or omit them freely. */
export interface RoleSummary {
  id: number;
  name: string;
  scopes: string[];
  grants_global_access: boolean;
  is_office_admin: boolean;
  is_operator: boolean;
  /** Discussed requirement — Menu Access (lib/menuItems.ts). `null` =
   * not customized (Sidebar falls back to its own scope/has_global_access-
   * derived default visibility per item); `[]` = deliberately show
   * nothing; a non-empty list = a strict allowlist of menu item keys. */
  visible_menu_items: string[] | null;
}

/** Step 4/6 (Office <-> Blast/Settings integration) — `office` is `null`
 * for a user with no Office membership (or a globally-accessing Role,
 * which deliberately has none). `has_global_access` is true for
 * Superadmin or a Role with `grants_global_access` — both see/act across
 * every Office. `role` is `null` for a Superadmin or anyone without a
 * membership row — used only to decide whether to show the Settings
 * admin UI for an Office-Admin-equivalent Role too (SettingsPage.tsx). */
export interface Me {
  id: number;
  username: string;
  display_name: string;
  is_superuser: boolean;
  has_global_access: boolean;
  office: { id: number; name: string } | null;
  role: RoleSummary | null;
  /** Step 14 — `null` for anyone without a membership row; only
   * meaningful alongside `role.is_operator`. */
  is_available: boolean | null;
  /** Discussed requirement — `''` for anyone who hasn't set one yet
   * (apps.offices.models.UserProfile, self-editable via /profile). Used
   * to append "- {initial}" to every manually-typed Inbox reply
   * (InboxPage.tsx's handleSend). */
  initial: string;
}

/** GET /api/auth/me/ — docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md
 * Section 4. Identifies the caller of the Django-issued JWT; called
 * directly against Django (Frontend -> Django), not through the BFF. */
export function getMe() {
  return request<Me>(`${config.djangoBaseUrl}/api/auth/me/`, { headers: authHeader() });
}

export interface MessageTrendBucket {
  hour: string;
  count: number;
}

export interface DashboardMessages {
  messages_today: number;
  trend: MessageTrendBucket[];
}

/** GET /api/dashboard/messages/ — today's message count and a 24-bucket
 * hourly trend, both for the UTC calendar day (see the Phase 8 backend
 * foundation report Section 7 — this project's only configured timezone
 * is UTC, so "today" has no other defined meaning here). */
export function getDashboardMessages() {
  return request<DashboardMessages>(`${config.djangoBaseUrl}/api/dashboard/messages/`, { headers: authHeader() });
}

export type ActivityItemType = 'audit' | 'webhook';

export interface ActivityItem {
  id: string;
  type: ActivityItemType;
  action: string;
  target: string;
  result: string;
  occurred_at: string;
}

export interface DashboardActivity {
  results: ActivityItem[];
}

/** GET /api/dashboard/activity/?limit=N — bounded, newest-first, merged
 * AuditLog/WebhookEvent feed. */
export function getDashboardActivity(limit: number) {
  return request<DashboardActivity>(`${config.djangoBaseUrl}/api/dashboard/activity/?limit=${limit}`, {
    headers: authHeader(),
  });
}

export interface PendingChat {
  id: number;
  provider_chat_id: string;
  contact_name: string | null;
  phone_number: string | null;
  office: { id: number; name: string } | null;
  waiting_since: string | null;
}

export interface PendingChatsResponse {
  count: number;
  results: PendingChat[];
}

/** GET /api/dashboard/pending-chats/ — Conversation/Bot Engine handoff
 * queue: unclaimed chats currently waiting for a human operator. An
 * Office Admin/Operator sees only their own Office's; a Superadmin/
 * Global Admin sees every Office's, plus any chat with no Office at all
 * (every Office currently declined direct chat, or none was ever
 * selected) — the one case only a globally-accessing actor can see. */
export function getPendingChats() {
  return request<PendingChatsResponse>(`${config.djangoBaseUrl}/api/dashboard/pending-chats/`, {
    headers: authHeader(),
  });
}

// Inbox/Chat (canonical Phase 8) — docs/generated/INBOX-CHAT-DECISION-REPORT.md.
// Frontend -> Django direct for reads (Section 1 of that report), matching
// the Dashboard precedent above. Sending a message is NOT here — it stays
// Frontend -> BFF -> WAHA via the existing sendText endpoint
// (see bffApi.ts's sendMessage()).

/** DRF's standard PageNumberPagination response envelope — this
 * project's first paginated endpoints. */
export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Step 14 (Operator assignment foundation) — `null` when the Chat has
 * no operator currently assigned. */
export interface AssignedOperator {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
}

export interface ChatSummary {
  id: number;
  provider_chat_id: string;
  name: string;
  is_group: boolean;
  contact_name: string | null;
  phone_number: string | null;
  last_message_at: string | null;
  last_read_at: string | null;
  unread: boolean;
  assigned_to: AssignedOperator | null;
  /** Conversation/Bot Engine — true while this Chat has a
   * ConversationSession handed off to a human operator (state
   * waiting_operator). Drives the "Tutup Sesi Bot" button; the server
   * re-checks this independently on close, this field only decides
   * whether to show the control. */
  waiting_for_operator: boolean;
  /** Whether the viewer may currently manage THIS chat (assign/unassign/
   * claim/close-session/reply) — false for an Office that used to own
   * this chat but no longer does (its own past history stays visible,
   * chats_visible_to's own docstring, but never editable). Always true
   * for Superadmin/Global Admin. Drives the composer and the assignment/
   * close-session controls alike — the server re-checks independently
   * on every mutating call, this field only decides what to show. */
  can_manage: boolean;
}

/** GET /api/chats/ — paginated, most-recently-active chat first.
 * Requires the JWT's `reading` scope (apps.authn.permissions.HasReadingScope). */
export function getChats(page = 1) {
  return request<PaginatedResponse<ChatSummary>>(`${config.djangoBaseUrl}/api/chats/?page=${page}`, {
    headers: authHeader(),
  });
}

export interface OperatorCandidate {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  is_available: boolean;
}

/** GET /api/chats/:id/operators/ — Step 14. Operators who may currently
 * be assigned this chat (real membership in the chat's own Office, role
 * operator, available, active). Requires HasOfficeAdminAccess
 * (Superadmin/Global Admin/Office Admin — never a plain Operator). */
export function getChatOperators(chatId: number) {
  return request<OperatorCandidate[]>(`${config.djangoBaseUrl}/api/chats/${chatId}/operators/`, {
    headers: authHeader(),
  });
}

/** POST /api/chats/:id/assign/ — body {user_id}. Server re-validates the
 * target against the database regardless of what getChatOperators()
 * previously returned. Returns the updated chat summary shape. */
export function assignChat(chatId: number, userId: number) {
  return request<ChatSummary>(`${config.djangoBaseUrl}/api/chats/${chatId}/assign/`, {
    method: 'POST',
    body: { user_id: userId },
    headers: authHeader(),
  });
}

/** POST /api/chats/:id/unassign/ — no body. Never removes the chat from
 * the Inbox; only clears assigned_to. */
export function unassignChat(chatId: number) {
  return request<ChatSummary>(`${config.djangoBaseUrl}/api/chats/${chatId}/unassign/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

/** POST /api/chats/:id/transfer/ — body {office_id, user_id}.
 * Superadmin/Global Admin only — moves the chat to a DIFFERENT Office
 * and a specific member of it in one step, even while a
 * WAITING_OPERATOR session is open (the one action exempt from the
 * "close the session first" rule assign/unassign enforce). */
export function transferChat(chatId: number, officeId: number, userId: number) {
  return request<ChatSummary>(`${config.djangoBaseUrl}/api/chats/${chatId}/transfer/`, {
    method: 'POST',
    body: { office_id: officeId, user_id: userId },
    headers: authHeader(),
  });
}

/** POST /api/chats/:id/claim/ — no body, always self-assigns the caller
 * (the "ambil" action for a pending chat surfaced on the Dashboard).
 * Returns `error.code` `already_claimed` (someone else got there first)
 * or `not_eligible` (not a valid claimant for this chat) on 400. */
export function claimChat(chatId: number) {
  return request<ChatSummary>(`${config.djangoBaseUrl}/api/chats/${chatId}/claim/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

/** POST /api/chats/:id/close-session/ — no body. Manually ends this
 * chat's waiting_operator ConversationSession — the bot resumes
 * answering the citizen's next message afterward. Returns an `error`
 * with code `no_active_session` (400) if this chat has no session
 * currently waiting for an operator. */
export function closeChatSession(chatId: number) {
  return request<ChatSummary>(`${config.djangoBaseUrl}/api/chats/${chatId}/close-session/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

/** PATCH /api/auth/me/availability/ — Step 14. Self-service only; the
 * server always targets the caller's own OfficeMembership. Only a real
 * role=operator membership may use this (403 otherwise). */
export function updateOperatorAvailability(isAvailable: boolean) {
  return request<{ is_available: boolean }>(`${config.djangoBaseUrl}/api/auth/me/availability/`, {
    method: 'PATCH',
    body: { is_available: isAvailable },
    headers: authHeader(),
  });
}

export interface MediaReferenceInfo {
  id: number;
  provider_media_id: string;
  mime_type: string;
  file_name: string;
}

export interface ChatMessage {
  id: number;
  provider_message_id: string;
  direction: 'inbound' | 'outbound';
  message_type: string;
  body: string;
  status: string;
  timestamp: string;
  media: MediaReferenceInfo[];
}

/** GET /api/chats/:id/messages/ — paginated, newest-first (matches
 * WAHA's own REST history convention). */
export function getChatMessages(chatId: number, page = 1) {
  return request<PaginatedResponse<ChatMessage>>(
    `${config.djangoBaseUrl}/api/chats/${chatId}/messages/?page=${page}`,
    { headers: authHeader() },
  );
}

export interface MarkChatReadResult {
  id: number;
  last_read_at: string;
}

/** POST /api/chats/:id/read/ — sets the chat's durable, UI-attention-only
 * read state to now. Never touches WAHA (docs/generated/INBOX-CHAT-DECISION-REPORT.md
 * Section 2). */
export function markChatRead(chatId: number) {
  return request<MarkChatReadResult>(`${config.djangoBaseUrl}/api/chats/${chatId}/read/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

// Sync status (Phase 9.1A/9.1E) — docs/generated/PHASE9-1A-SYNC-STATUS-IMPLEMENTATION-REPORT.md,
// docs/generated/PHASE9-1E-DESIGN-AUDIT-REPORT.md Section 10. Read-only;
// never touches WAHA/Redis/Celery and never triggers reconciliation.

export interface SyncStatus {
  session: string;
  sync_status: 'never_synced' | 'running' | 'failed' | 'healthy' | 'stale';
  checkpoint_status: string | null;
  last_run_at: string | null;
  seconds_since_last_run: number | null;
  checkpoint_updated_at: string | null;
  // Phase 13.B — docs/generated/PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md
  // Section 4/3. Both already returned by SyncStatusView today; the type
  // was simply stale relative to the backend response until this change.
  // `possibly_stuck` is a heuristic signal (see mapSyncStatus below), not
  // proof a run has failed. `last_webhook_received_at` is included for
  // type accuracy only — no UI in this phase renders it (no existing,
  // established place in InboxPage.tsx it naturally belongs).
  possibly_stuck: boolean;
  last_webhook_received_at: string | null;
}

/** GET /api/sync/status/:session/ — a session that Django doesn't know
 * about at all resolves as a 404 (ApiError.kind: 'not_found'), which the
 * caller (InboxPage.tsx) treats the same as 'never_synced' — see
 * PHASE9-1E-DESIGN-AUDIT-REPORT.md Section 9. Not a connectivity error. */
export function getSyncStatus(session: string) {
  return request<SyncStatus>(`${config.djangoBaseUrl}/api/sync/status/${encodeURIComponent(session)}/`, {
    headers: authHeader(),
  });
}

export interface SyncCheckpointRecoveryResult {
  recovered: boolean;
  previous_status: string;
  status: string;
}

/** POST /api/sync/recover/:session/ — manual, human-triggered recovery
 * (Phase 13.A: backend/apps/sync/views.py SyncCheckpointRecoveryView).
 * Frontend -> Django direct, same as getSyncStatus above — never routed
 * through the BFF (docs/generated/PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md
 * Section 2.1). Server-side authorization (`IsAuthenticated` +
 * `HasSystemAdministrationScope`) is the actual security boundary; the
 * caller (InboxPage.tsx) hiding the triggering button for non-admin users
 * is a UX courtesy only, not the enforcement mechanism. Does not enqueue
 * a replacement reconciliation run — marks the current run as failed so a
 * future run can start cleanly. */
export function recoverSyncCheckpoint(session: string) {
  return request<SyncCheckpointRecoveryResult>(
    `${config.djangoBaseUrl}/api/sync/recover/${encodeURIComponent(session)}/`,
    { method: 'POST', headers: authHeader() },
  );
}

// Blast (Phase 11) — backend/apps/blast/{models,serializers,views,urls}.py,
// mounted at /api/blast/ (backend/config/urls.py). Frontend -> Django
// direct, same trust boundary as Inbox/Chat and sync-status above (these
// are JWTAuthentication endpoints for a logged-in human's browser, not
// BFF-internal traffic) — see apps/blast/views.py's own module docstring.
//
// Every field below is taken verbatim from the real serializers, not the
// design audit narrative:
//   - BlastRecipientSerializer (serializers.py:9-13): id, destination,
//     status, scheduled_for, sent_at, failure_reason — all read-only.
//   - BlastCampaignListSerializer (serializers.py:70-84): id, session
//     (session name string, not an FK id), name, status, recipient_count
//     (a SerializerMethodField — NOT a stored column), created_by/
//     approved_by (usernames), approved_at, created_at, updated_at.
//   - BlastCampaignDetailSerializer (serializers.py:87-91) extends the
//     list serializer with message_template, rejected_reason, recipients.
//   - BlastCampaignCreateSerializer (serializers.py:16-67): request body
//     is {session (name string), name, message_template, recipients
//     (string[] of destinations, max BLAST_MAX_RECIPIENTS_PER_CAMPAIGN)};
//     response is the *detail* shape (views.py:83).
//   - BlastCampaignRejectSerializer (serializers.py:94-95): reason is
//     OPTIONAL (default ''), not required — the reject UI below must not
//     force one.
// There is no stored `idempotency_key` field (models.py:11-16 — it's a
// derived @property, never serialized) and no submitted/sending/
// completed/failed timestamp columns on BlastCampaign (models.py:71-86
// only has created_at/updated_at from TimeStampedModel plus approved_at)
// — the frontend only shows created_at/approved_at/updated_at, never a
// fabricated per-transition timestamp.

export type BlastCampaignStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'sending'
  | 'completed'
  | 'rejected'
  | 'failed';

// Discussed requirement — Blast Templates + per-recipient variables +
// External API. `invalid_number` is a new terminal BlastRecipient status
// (models.py's STATUS_INVALID_NUMBER) for a number confirmed NOT to be
// on WhatsApp, checked before a send is ever attempted — distinct from
// `failed` (a send was attempted and failed). `template`/`source` on the
// campaign shapes and `variables` on the recipient shape are all
// additive (serializers.py's BlastCampaignListSerializer.get_template/
// get_source, BlastRecipientSerializer's `variables` field).
export type BlastRecipientStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'skipped' | 'invalid_number';

export type BlastCampaignSource = 'dashboard' | 'api';

export interface BlastRecipient {
  id: number;
  destination: string;
  status: BlastRecipientStatus;
  scheduled_for: string | null;
  sent_at: string | null;
  failure_reason: string;
  variables: Record<string, string>;
}

export interface BlastCampaignListItem {
  id: number;
  session: string;
  name: string;
  status: BlastCampaignStatus;
  recipient_count: number;
  created_by: string;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  /** Step 4 (Blast <-> Office integration) — `null` for a legacy campaign
   * created before Office was introduced (no backfill was performed). */
  office: { id: number; name: string } | null;
  /** `null` for a freeform campaign never created from a template. */
  template: { id: number; key: string; name: string } | null;
  /** 'api' when `triggered_by_api_key` is set (an external-system-
   * triggered, auto-approved campaign), 'dashboard' otherwise. */
  source: BlastCampaignSource;
}

export interface BlastCampaignDetail extends BlastCampaignListItem {
  message_template: string;
  rejected_reason: string;
  recipients: BlastRecipient[];
}

/** GET /api/blast/campaigns/ — readable by either the 'blast' scope
 * (creators need to see their own campaigns) or 'system administration'
 * (approvers need to see everything pending approval); no query params —
 * the backend returns every campaign, newest-first (views.py:66-69). */
export function getBlastCampaigns() {
  return request<BlastCampaignListItem[]>(`${config.djangoBaseUrl}/api/blast/campaigns/`, {
    headers: authHeader(),
  });
}

/** GET /api/blast/campaigns/:id/ — same read-access rule as the list. */
export function getBlastCampaign(id: number) {
  return request<BlastCampaignDetail>(`${config.djangoBaseUrl}/api/blast/campaigns/${id}/`, {
    headers: authHeader(),
  });
}

/** A per-recipient row for the template path — `destination` plus every
 * `{{variable}}` the chosen template declares (serializers.py's
 * `validate()`: ANY row missing/mismatching a variable rejects the
 * WHOLE request, never a partial create). */
export interface BlastRecipientInput {
  destination: string;
  variables: Record<string, string>;
}

export interface CreateBlastCampaignInput {
  session: string;
  name: string;
  /** Required for the freeform path (no `template`); ignored server-side
   * (overwritten with the template's own content) when `template` is
   * given — see serializers.py's `validate()`. */
  message_template?: string;
  /** Bare destination strings (freeform, additive/original path) OR
   * `{destination, variables}` objects (required once `template` is
   * set) — never mixed within one request in practice, but the type
   * itself allows either shape per item, matching the backend's own
   * mixed-shape `ListField`. */
  recipients: Array<string | BlastRecipientInput>;
  /** Discussed requirement — Blast Templates. When set, `content` is
   * snapshotted server-side into `message_template`; every recipient
   * must then be a `BlastRecipientInput` carrying exactly this
   * template's declared variables. */
  template?: number;
  /** Step 4 (Blast <-> Office integration) — only meaningful for a
   * globally-accessing user (Superadmin/Global Admin), who must pick an
   * Office explicitly. For everyone else the backend ignores whatever is
   * sent here and forces the caller's own Office (serializers.py
   * validate()) — so this is omitted entirely for non-global users. */
  office?: number;
}

/** The all-or-nothing per-row validation failure shape
 * (serializers.py's `validate()`: `{recipients: str, details: [...]}`,
 * surfaced by `lib/api.ts` as an ApiError with this as `.details`). */
export interface BlastRecipientValidationDetail {
  index: number;
  destination: string;
  missing: string[];
  extra: string[];
}

/** POST /api/blast/campaigns/ — creates a `draft` campaign (requires the
 * 'blast' scope). Recipient de-duplication and the
 * BLAST_MAX_RECIPIENTS_PER_CAMPAIGN cap are enforced server-side
 * (serializers.py:45-58); the frontend's own cap check is a UX courtesy
 * only, matching this codebase's existing discipline (e.g. Inbox/
 * Sessions' scope-gated buttons). Returns the detail shape. */
export function createBlastCampaign(input: CreateBlastCampaignInput) {
  return request<BlastCampaignDetail>(`${config.djangoBaseUrl}/api/blast/campaigns/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

export interface OfficeChoice {
  id: number;
  name: string;
}

/** GET /api/blast/offices/ — Step 4 (Blast <-> Office integration): the
 * Office picker's data source for a globally-accessing user creating a
 * campaign. Gated server-side to `has_global_access` (403 otherwise) —
 * this is NOT a general Office-management endpoint (views.py's
 * BlastOfficeChoicesView). */
export function listOffices() {
  return request<OfficeChoice[]>(`${config.djangoBaseUrl}/api/blast/offices/`, {
    headers: authHeader(),
  });
}

/** POST /api/blast/campaigns/:id/submit/ — draft -> pending_approval.
 * Restricted server-side to the campaign's own creator (views.py:119-120,
 * a 403 'forbidden' ApiError otherwise). */
export function submitBlastCampaign(id: number) {
  return request<BlastCampaignDetail>(`${config.djangoBaseUrl}/api/blast/campaigns/${id}/submit/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

/** POST /api/blast/campaigns/:id/approve/ — pending_approval -> approved,
 * requires 'system administration'; server-side also rejects the
 * campaign's own creator (403) and a campaign whose recipient count would
 * exceed the session's remaining daily budget (409 'daily_budget_exceeded',
 * views.py:161-179 — surfaced here as an ApiError.kind: 'validation' with
 * the backend's own message, per the existing 400/409 -> 'validation'
 * mapping in lib/api.ts). Triggers dispatch scheduling server-side; this
 * call itself never touches BFF/WAHA. */
export function approveBlastCampaign(id: number) {
  return request<BlastCampaignDetail>(`${config.djangoBaseUrl}/api/blast/campaigns/${id}/approve/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

/** POST /api/blast/campaigns/:id/reject/ — pending_approval -> rejected,
 * requires 'system administration'. `reason` is OPTIONAL server-side
 * (BlastCampaignRejectSerializer: allow_blank, default '') — always sent,
 * possibly empty, never required client-side either. */
export function rejectBlastCampaign(id: number, reason: string) {
  return request<BlastCampaignDetail>(`${config.djangoBaseUrl}/api/blast/campaigns/${id}/reject/`, {
    method: 'POST',
    body: { reason },
    headers: authHeader(),
  });
}

/** POST /api/blast/campaigns/:id/recipients/:recipientId/resolve/ — Phase
 * 11 stuck-recovery fix (docs/generated/PHASE-11-BLAST-STUCK-RECOVERY-IMPLEMENTATION-REPORT.md):
 * manually transitions a `sending` recipient (worker died after the WAHA
 * send but before the final status write — never self-healing, per
 * decision 6) to a terminal status the admin has determined externally.
 * Requires 'system administration'. Compare-and-set server-side
 * (views.py's BlastRecipientResolveView) — a 409 'not_sending' or
 * 'concurrent_state_change' ApiError if the recipient already moved on.
 * Never calls the BFF/WAHA client (a pure status write). Returns the
 * updated campaign detail, same shape as approve/reject, so the campaign
 * can finalize to completed/failed in the same response if this was its
 * last in-flight recipient. */
export function resolveBlastRecipient(campaignId: number, recipientId: number, status: 'sent' | 'failed') {
  return request<BlastCampaignDetail>(
    `${config.djangoBaseUrl}/api/blast/campaigns/${campaignId}/recipients/${recipientId}/resolve/`,
    {
      method: 'POST',
      body: { status },
      headers: authHeader(),
    },
  );
}

// ---------------------------------------------------------------------
// Blast Templates + API Keys + Settings + History — Discussed
// requirement (vehicle-tax due-date reminders). All mounted under
// /api/blast/ alongside campaigns above (apps/blast/urls.py), same
// JWTAuthentication trust boundary.

export interface BlastTemplate {
  id: number;
  key: string;
  name: string;
  content: string;
  /** Derived server-side from `content` (apps.blast.templating.
   * extract_variable_names) — never a second, hand-maintained copy. */
  variable_names: string[];
  /** `null` = a shared/global template, usable by every Office. */
  office: number | null;
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** GET /api/blast/templates/ — readable by 'blast' or 'system
 * administration', office-scoped (own Office's templates + every global
 * one) unless the caller is globally-accessing (apps.blast.authorization.
 * templates_visible_to). */
export function getBlastTemplates() {
  return request<BlastTemplate[]>(`${config.djangoBaseUrl}/api/blast/templates/`, {
    headers: authHeader(),
  });
}

export interface CreateBlastTemplateInput {
  key: string;
  name: string;
  content: string;
  /** Only meaningful for a globally-accessing user, who may explicitly
   * create a shared/global template (`office: null`) or scope it to one
   * Office. Ignored/overwritten server-side for everyone else, who
   * always gets their own Office forced (views.py's
   * BlastTemplateListCreateView.post). */
  office?: number | null;
}

/** POST /api/blast/templates/ — requires 'blast'. */
export function createBlastTemplate(input: CreateBlastTemplateInput) {
  return request<BlastTemplate>(`${config.djangoBaseUrl}/api/blast/templates/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

/** PATCH /api/blast/templates/:id/ — `key` is stable-by-design and
 * silently ignored server-side even if sent (views.py's
 * BlastTemplateDetailView.patch); every other field may change freely.
 * No DELETE — retire a template via `is_active: false` instead (same
 * "revoke, never hard-delete" convention as BlastApiKey below). */
export function updateBlastTemplate(id: number, input: Partial<Omit<CreateBlastTemplateInput, 'key'>> & { is_active?: boolean }) {
  return request<BlastTemplate>(`${config.djangoBaseUrl}/api/blast/templates/${id}/`, {
    method: 'PATCH',
    body: input,
    headers: authHeader(),
  });
}

/** List-shape for GET /api/blast/api-keys/ — never includes the raw key
 * (shown exactly once, only in CreateBlastApiKeyResult below).
 * Discussed requirement — a key is GLOBAL and carries no Office at all
 * (works for any session named in each external request — see
 * apps.blast.models.BlastApiKey's own docstring). */
export interface BlastApiKey {
  id: number;
  name: string;
  key_prefix: string;
  is_active: boolean;
  created_by: string;
  last_used_at: string | null;
  created_at: string;
}

/** GET /api/blast/api-keys/ — Superadmin/Global-Admin-only (403
 * otherwise), same gating precedent as the Roles tab. */
export function getBlastApiKeys() {
  return request<BlastApiKey[]>(`${config.djangoBaseUrl}/api/blast/api-keys/`, {
    headers: authHeader(),
  });
}

export interface CreateBlastApiKeyResult {
  id: number;
  name: string;
  key_prefix: string;
  is_active: boolean;
  /** Shown exactly once, in THIS response only — never retrievable
   * again afterward (apps.blast.models.BlastApiKey's own docstring). */
  raw_key: string;
}

/** POST /api/blast/api-keys/ — creates a new external-API credential.
 * Global by design: works for a single ad-hoc message, a freeform
 * blast, or a templated blast, against ANY session named in each
 * request. */
export function createBlastApiKey(name: string) {
  return request<CreateBlastApiKeyResult>(`${config.djangoBaseUrl}/api/blast/api-keys/`, {
    method: 'POST',
    body: { name },
    headers: authHeader(),
  });
}

/** POST /api/blast/api-keys/:id/revoke/ — `is_active: false`, never a
 * hard delete (past campaigns stay attributable to a revoked key). */
export function revokeBlastApiKey(id: number) {
  return request<void>(`${config.djangoBaseUrl}/api/blast/api-keys/${id}/revoke/`, {
    method: 'POST',
    headers: authHeader(),
  });
}

export interface BlastSettings {
  inter_message_delay_seconds: number;
}

/** GET /api/blast/settings/ — the one-row dynamic-delay singleton,
 * Superadmin/Global-Admin-only. Applies to EVERY campaign (dashboard and
 * API-triggered alike) — a single setting, not two. */
export function getBlastSettings() {
  return request<BlastSettings>(`${config.djangoBaseUrl}/api/blast/settings/`, {
    headers: authHeader(),
  });
}

export function updateBlastSettings(inter_message_delay_seconds: number) {
  return request<BlastSettings>(`${config.djangoBaseUrl}/api/blast/settings/`, {
    method: 'PATCH',
    body: { inter_message_delay_seconds },
    headers: authHeader(),
  });
}

/** One flattened row of GET /api/blast/history/ — a BlastRecipient
 * across ANY campaign, with just enough of its parent campaign inlined
 * for the History table's columns/filters (views.py's BlastHistoryView).
 * This — never the Inbox — is where a blast message's outcome is
 * actually visible/auditable (Discussed requirement). */
export interface BlastHistoryItem {
  id: number;
  destination: string;
  status: BlastRecipientStatus;
  failure_reason: string;
  variables: Record<string, string>;
  sent_at: string | null;
  created_at: string;
  campaign: {
    id: number;
    name: string;
    office: { id: number; name: string } | null;
    template: { id: number; name: string } | null;
    source: BlastCampaignSource;
  };
}

export interface BlastHistoryQuery {
  search?: string;
  status?: BlastRecipientStatus;
  /** Superadmin/Global Admin only — ignored server-side otherwise (an
   * Office-scoped caller is already limited to their own Office). */
  office?: number;
  template?: number;
  source?: BlastCampaignSource;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface BlastHistoryResponse {
  count: number;
  num_pages: number;
  page: number;
  results: BlastHistoryItem[];
}

/** GET /api/blast/history/ — server-side paginated + filterable, the
 * same PageNumberPagination-style envelope shape already established
 * for e.g. GET /api/chats/ (ChatListView). */
export function getBlastHistory(query: BlastHistoryQuery = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return request<BlastHistoryResponse>(`${config.djangoBaseUrl}/api/blast/history/${qs ? `?${qs}` : ''}`, {
    headers: authHeader(),
  });
}

// ---------------------------------------------------------------------
// Step 6 — Office & User management (apps/offices/views.py). Only
// reachable server-side by a globally-accessing administrator
// (Superadmin/Global Admin, for Office management) or an admin with the
// 'user administration' scope (Office/Global Admin, for User
// management) — this client never enforces that itself; the frontend
// only decides whether to *show* the Settings admin UI (SettingsPage.tsx),
// same "frontend is not the security boundary" discipline as every
// other page in this file.
// ---------------------------------------------------------------------

export interface Office {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** GET /api/offices/ — every Office, active and inactive (OfficeListCreateView).
 * Deliberately NOT server-side paginated, unlike `getUsers` — Offices is
 * a small, slow-growing catalog reused as a FULL-list dropdown source by
 * several other forms (User form's Office picker, Blast/Inbox-config/
 * Bot-config Office pickers); paginating it would break every one of
 * those. */
export function getOffices() {
  return request<Office[]>(`${config.djangoBaseUrl}/api/offices/`, { headers: authHeader() });
}

/** POST /api/offices/ — create an Office. `name` must be unique (409/400
 * from the server otherwise, surfaced as the usual ApiError). */
export function createOffice(name: string) {
  return request<Office>(`${config.djangoBaseUrl}/api/offices/`, {
    method: 'POST',
    body: { name },
    headers: authHeader(),
  });
}

/** PATCH /api/offices/:id/ — update name and/or is_active. Deactivating
 * an Office does not delete or cascade anything; it only stops it from
 * being selectable for a *new* Blast campaign (BlastCampaignCreateSerializer). */
export function updateOffice(id: number, patch: Partial<Pick<Office, 'name' | 'is_active'>>) {
  return request<Office>(`${config.djangoBaseUrl}/api/offices/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

/** Step 10 — per-Office Inbox configuration FOUNDATION. Saving this
 * never sends a message or drives any WhatsApp flow — no backend code
 * reads this model for that yet (OfficeInboxConfigView's own docstring).
 * `Office.is_active` and `enabled` are independent: an inactive Office
 * may still have `enabled: true` saved here. */
export interface OfficeInboxConfig {
  enabled: boolean;
  welcome_message: string;
  waiting_message: string;
  offline_message: string;
  created_at: string;
  updated_at: string;
}

/** GET /api/offices/:id/inbox-config/ — lazily created server-side on
 * first read (safe defaults: enabled=false, empty messages) — never
 * requires a separate "create" call. */
export function getOfficeInboxConfig(officeId: number) {
  return request<OfficeInboxConfig>(`${config.djangoBaseUrl}/api/offices/${officeId}/inbox-config/`, {
    headers: authHeader(),
  });
}

export type UpdateOfficeInboxConfigInput = Partial<
  Pick<OfficeInboxConfig, 'enabled' | 'welcome_message' | 'waiting_message' | 'offline_message'>
>;

/** PATCH /api/offices/:id/inbox-config/ — Superadmin/Global Admin for
 * any Office, an Office Admin only their own (OfficeInboxConfigView's
 * `_admin_scope` check — same helper as every other Office/User admin
 * endpoint). */
export function updateOfficeInboxConfig(officeId: number, patch: UpdateOfficeInboxConfigInput) {
  return request<OfficeInboxConfig>(`${config.djangoBaseUrl}/api/offices/${officeId}/inbox-config/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

export interface AdminUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_superuser: boolean;
  /** `null` for a Superadmin (no OfficeMembership row at all). Carries
   * BOTH organizational standing and feature/scope access (the Role
   * merge) — see `RoleSummary`'s own comment. */
  role: RoleSummary | null;
  /** `null` for a globally-accessing Role (by design — not tied to one
   * Office) or a Superadmin. */
  office: { id: number; name: string } | null;
  /** Discussed requirement — short signature (e.g. "RD") set at
   * creation, shown to a citizen when this user claims a chat. `''` for
   * a user created before this field existed (never backfilled). */
  initial: string;
  date_joined: string;
}

/** GET /api/users/ — users visible to the caller's admin scope: all of
 * them for Superadmin/Global Admin, only the caller's own Office's users
 * for an Office Admin (UserListCreateView). Server-side paginated (DRF
 * `PageNumberPagination`, same envelope `getChats` already uses) — the
 * one Settings admin table that can realistically grow large.
 * `Offices`/`Roles` deliberately stay unpaginated (see their own
 * comments) since other forms need their FULL list as dropdown data. For
 * a call site that genuinely needs every User too (InboxPage.tsx's
 * cross-Office transfer picker), use `getAllUsers()` below instead of
 * calling this directly. */
export interface UsersQuery {
  page?: number;
  /** Case-insensitive substring match against username/first_name/last_name
   * (`UserListCreateView.get`'s own `search` param). */
  search?: string;
  /** An Office id. */
  office?: number;
  /** A Role id. */
  role?: number;
  isActive?: boolean;
}

export function getUsers(query: UsersQuery = {}) {
  const params = new URLSearchParams();
  params.set('page', String(query.page ?? 1));
  if (query.search) params.set('search', query.search);
  if (query.office != null) params.set('office', String(query.office));
  if (query.role != null) params.set('role', String(query.role));
  if (query.isActive != null) params.set('is_active', String(query.isActive));
  return request<PaginatedResponse<AdminUser>>(`${config.djangoBaseUrl}/api/users/?${params.toString()}`, {
    headers: authHeader(),
  });
}

/** Loops `getUsers()` across every page and concatenates — for the rare
 * picker use case that needs the FULL user list client-side (unlike a
 * display table, which should always show one page at a time via
 * `getUsers(page)` directly). Not used by SettingsUsersPanel.tsx. */
export async function getAllUsers(): Promise<ApiResult<AdminUser[]>> {
  const all: AdminUser[] = [];
  let page = 1;
  for (;;) {
    const result = await getUsers({ page });
    if (!result.ok) return result;
    all.push(...result.data.results);
    if (!result.data.next) break;
    page += 1;
  }
  return { ok: true, data: all };
}

export function getUser(id: number) {
  return request<AdminUser>(`${config.djangoBaseUrl}/api/users/${id}/`, { headers: authHeader() });
}

export interface CreateUserInput {
  username: string;
  password: string;
  first_name?: string;
  last_name?: string;
  /** Required — letters/digits/dot/underscore, at least 1 character
   * (server-enforced; see USERNAME_PATTERN's own comment for why). */
  initial: string;
  /** A Role id. Required for a non-globally-accessing Role; omit (or
   * send null) `office` for a Role with `grants_global_access`. Only a
   * globally-accessing actor may pick a Role that itself has
   * `grants_global_access` — the server 403s an Office Admin who tries. */
  role: number;
  office?: number | null;
}

/** POST /api/users/ — creates a Django User plus its OfficeMembership in
 * one call. Never creates a Superadmin — there is no `is_superuser`
 * field here or anywhere else in this API; that stays a Django-only
 * action. An Office Admin's own Office is forced server-side regardless
 * of what `office` is sent (UserCreateSerializer.validate()). */
export function createUser(input: CreateUserInput) {
  return request<AdminUser>(`${config.djangoBaseUrl}/api/users/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

export interface UpdateUserInput {
  first_name?: string;
  last_name?: string;
  password?: string;
  is_active?: boolean;
  initial?: string;
  /** `role` (a Role id) and `office` must be sent together
   * (UserDetailView.patch) — omit both to leave Office role/membership
   * untouched. Only a globally-accessing actor may pick a Role with
   * `grants_global_access` — the server 403s an Office Admin who tries. */
  role?: number;
  office?: number | null;
}

/** PATCH /api/users/:id/ — profile fields and/or role+office. The
 * server rejects a caller targeting their own account here (403) unless
 * they are a Superadmin, and rejects an Office Admin acting outside
 * their own Office or attempting to assign a globally-accessing Role
 * (403). */
export function updateUser(id: number, patch: UpdateUserInput) {
  return request<AdminUser>(`${config.djangoBaseUrl}/api/users/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

export interface MyProfile {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  initial: string;
}

/** GET /api/auth/me/profile/ — discussed requirement: every role's own
 * self-service profile (name, initial). Always the caller's own row. */
export function getMyProfile() {
  return request<MyProfile>(`${config.djangoBaseUrl}/api/auth/me/profile/`, { headers: authHeader() });
}

export interface UpdateMyProfileInput {
  first_name?: string;
  last_name?: string;
  initial?: string;
  /** Both required together to change the password — server rejects
   * `new_password` without `current_password` (re-authentication, not
   * just an active session). */
  current_password?: string;
  new_password?: string;
}

/** PATCH /api/auth/me/profile/ — self-service only; always the caller's
 * own row. Returns `error.code` `invalid_password` (400) if
 * `current_password` doesn't match when changing the password. */
export function updateMyProfile(patch: UpdateMyProfileInput) {
  return request<MyProfile>(`${config.djangoBaseUrl}/api/auth/me/profile/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

// --- Dynamic Roles ("Role x Scope" feature) -------------------------------
// `/api/roles/` (RoleListCreateView/RoleDetailView) — Superuser-only
// server-side (`IsSuperuser`, not any JWT scope): a Role's `scopes` list
// decides what the users it's assigned to may do (`_sync_role_groups`
// keeps their Django Groups, and so their JWT `scopes` claim, in sync).
// `scopes` is always a subset of the same 6 fixed strings
// `settings.JWT_SCOPES` declares backend-side — never freeform.

export interface Role extends RoleSummary {
  created_at: string;
  updated_at: string;
}

/** Deliberately NOT server-side paginated, same reasoning as `getOffices`
 * — the User form's own Role picker (SettingsUsersPanel.tsx) needs the
 * FULL catalog, not one page of it. */
export function getRoles() {
  return request<Role[]>(`${config.djangoBaseUrl}/api/roles/`, { headers: authHeader() });
}

export interface RoleInput {
  name: string;
  scopes: string[];
  grants_global_access?: boolean;
  is_office_admin?: boolean;
  is_operator?: boolean;
  /** Discussed requirement — Menu Access. Omitted/undefined leaves the
   * existing value untouched (PATCH semantics); `null` explicitly resets
   * back to "not customized"; `[]` or a list sets an explicit override —
   * see `RoleSummary.visible_menu_items`'s own comment for the meaning
   * of each. */
  visible_menu_items?: string[] | null;
}

export function createRole(input: RoleInput) {
  return request<Role>(`${config.djangoBaseUrl}/api/roles/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

export function updateRole(id: number, patch: Partial<RoleInput>) {
  return request<Role>(`${config.djangoBaseUrl}/api/roles/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

/** DELETE /api/roles/:id/ — the server returns a 400 `validation` error
 * (not a raw 500) if any user is still assigned this Role; reassign or
 * clear it from them first. */
export function deleteRole(id: number) {
  return request<{ deleted: true }>(`${config.djangoBaseUrl}/api/roles/${id}/`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

// --- Conversation/Bot Engine ------------------------------------------
// `/api/bot/` — `office` omitted (or `undefined`) everywhere below means
// the GLOBAL (shared, office=null) resource; a numeric `office` means
// that specific Office's own resource. Same `_admin_scope`-style
// authorization every other admin endpoint uses: Superadmin/Global Admin
// reach any scope, an Office Admin only their own Office's.

export interface BotConfig {
  id: number;
  office: number | null;
  enabled: boolean;
  fallback_message: string;
  session_completed_message: string;
  root_menu: number | null;
  /** Discussed requirement — Conversation/Bot Engine interactive list
   * menus (WAHA's `sendList`). Shown on every menu this bot sends as a
   * list. `list_footer_text` may be blank; `list_button_text` defaults
   * server-side to "Pilih" if left blank. */
  list_footer_text: string;
  list_button_text: string;
  /** Discussed requirement — human-like reply delay. `0` (default) sends
   * immediately, exactly as before this field existed. A positive value
   * (seconds) makes the bot show WhatsApp's "typing…" indicator for that
   * long before actually sending each automated reply. */
  reply_delay_seconds: number;
  created_at: string;
  updated_at: string;
}

/** GET /api/bot/config/?office=:id — omit `office` for the GLOBAL
 * config. Lazily created server-side on first read, same pattern as
 * `getOfficeInboxConfig`. */
export function getBotConfig(officeId?: number) {
  const qs = officeId != null ? `?office=${officeId}` : '';
  return request<BotConfig>(`${config.djangoBaseUrl}/api/bot/config/${qs}`, { headers: authHeader() });
}

export type UpdateBotConfigInput = Partial<
  Pick<
    BotConfig,
    | 'enabled'
    | 'fallback_message'
    | 'session_completed_message'
    | 'root_menu'
    | 'list_footer_text'
    | 'list_button_text'
    | 'reply_delay_seconds'
  >
>;

export function updateBotConfig(officeId: number | undefined, patch: UpdateBotConfigInput) {
  const qs = officeId != null ? `?office=${officeId}` : '';
  return request<BotConfig>(`${config.djangoBaseUrl}/api/bot/config/${qs}`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

export const BOT_ACTION_SEND_TEXT = 'send_text';
export const BOT_ACTION_SHOW_MENU = 'show_menu';
export const BOT_ACTION_COMPLETE_SESSION = 'complete_session';
export const BOT_ACTION_HANDOFF_TO_OPERATOR = 'handoff_to_operator';

export type BotMenuItemActionType =
  | typeof BOT_ACTION_SEND_TEXT
  | typeof BOT_ACTION_SHOW_MENU
  | typeof BOT_ACTION_COMPLETE_SESSION
  | typeof BOT_ACTION_HANDOFF_TO_OPERATOR;

export interface BotMenuItem {
  id: number;
  menu: number;
  label: string;
  trigger_value: string;
  order: number;
  enabled: boolean;
  action_type: BotMenuItemActionType;
  /** SEND_TEXT only. */
  text: string;
  /** SHOW_MENU only — required by the server when action_type is show_menu. */
  target_menu: number | null;
}

export interface BotMenu {
  id: number;
  office: number | null;
  name: string;
  parent_menu: number | null;
  intro_text: string;
  /** When true, this menu's options are NOT stored `items` — they are
   * built dynamically from the same Office list "Hubungi Petugas" has
   * always used (`available_operator_chat_offices()`), reused verbatim
   * server-side. `items` is expected to stay empty for such a menu. */
  is_office_selector: boolean;
  enabled: boolean;
  items: BotMenuItem[];
}

export function getBotMenus(officeId?: number) {
  const qs = officeId != null ? `?office=${officeId}` : '';
  return request<BotMenu[]>(`${config.djangoBaseUrl}/api/bot/menus/${qs}`, { headers: authHeader() });
}

export interface BotMenuInput {
  name: string;
  office?: number | null;
  parent_menu?: number | null;
  intro_text?: string;
  is_office_selector?: boolean;
  enabled?: boolean;
}

export function createBotMenu(input: BotMenuInput) {
  return request<BotMenu>(`${config.djangoBaseUrl}/api/bot/menus/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

export function updateBotMenu(id: number, patch: Partial<BotMenuInput>) {
  return request<BotMenu>(`${config.djangoBaseUrl}/api/bot/menus/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

/** DELETE /api/bot/menus/:id/ — the server returns a 400 `invalid` error
 * (not a raw 500) if this menu is still referenced by a menu item,
 * trigger, bot config, or an in-progress conversation session. */
export function deleteBotMenu(id: number) {
  return request<{ deleted: true }>(`${config.djangoBaseUrl}/api/bot/menus/${id}/`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

export interface BotMenuItemInput {
  label: string;
  trigger_value: string;
  order?: number;
  enabled?: boolean;
  action_type: BotMenuItemActionType;
  text?: string;
  target_menu?: number | null;
}

export function createBotMenuItem(menuId: number, input: BotMenuItemInput) {
  return request<BotMenuItem>(`${config.djangoBaseUrl}/api/bot/menus/${menuId}/items/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

/** PATCH /api/bot/items/:id/ — cannot move an item to a different menu
 * (the server silently drops a `menu` field in the payload); create a
 * new item under the target menu and delete this one instead. */
export function updateBotMenuItem(id: number, patch: Partial<BotMenuItemInput>) {
  return request<BotMenuItem>(`${config.djangoBaseUrl}/api/bot/items/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

export function deleteBotMenuItem(id: number) {
  return request<{ deleted: true }>(`${config.djangoBaseUrl}/api/bot/items/${id}/`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}

export interface BotTrigger {
  id: number;
  office: number | null;
  keyword: string;
  target_menu: number | null;
  enabled: boolean;
}

export function getBotTriggers(officeId?: number) {
  const qs = officeId != null ? `?office=${officeId}` : '';
  return request<BotTrigger[]>(`${config.djangoBaseUrl}/api/bot/triggers/${qs}`, { headers: authHeader() });
}

export interface BotTriggerInput {
  keyword: string;
  office?: number | null;
  target_menu: number | null;
  enabled?: boolean;
}

export function createBotTrigger(input: BotTriggerInput) {
  return request<BotTrigger>(`${config.djangoBaseUrl}/api/bot/triggers/`, {
    method: 'POST',
    body: input,
    headers: authHeader(),
  });
}

export function updateBotTrigger(id: number, patch: Partial<BotTriggerInput>) {
  return request<BotTrigger>(`${config.djangoBaseUrl}/api/bot/triggers/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}

export function deleteBotTrigger(id: number) {
  return request<{ deleted: true }>(`${config.djangoBaseUrl}/api/bot/triggers/${id}/`, {
    method: 'DELETE',
    headers: authHeader(),
  });
}
