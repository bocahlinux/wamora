import { authHeader } from './auth';
import { config } from './config';
import { request } from './api';

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

/** Step 4/6 (Office <-> Blast/Settings integration) — `office` is `null`
 * for a user with no Office membership (or a Global Admin, who
 * deliberately has none). `has_global_access` is true for Superadmin or
 * Global Admin — both see/act across every Office. `role` is `null` for
 * a Superadmin/Operator/no-membership user — used only to decide whether
 * to show the Settings admin UI for an Office Admin too (SettingsPage.tsx). */
export interface Me {
  id: number;
  username: string;
  display_name: string;
  is_superuser: boolean;
  has_global_access: boolean;
  office: { id: number; name: string } | null;
  role: 'global_admin' | 'office_admin' | 'operator' | null;
  /** Step 14 — `null` for anyone without a membership row; only
   * meaningful alongside `role === 'operator'`. */
  is_available: boolean | null;
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

export type BlastRecipientStatus = 'pending' | 'sending' | 'sent' | 'failed' | 'skipped';

export interface BlastRecipient {
  id: number;
  destination: string;
  status: BlastRecipientStatus;
  scheduled_for: string | null;
  sent_at: string | null;
  failure_reason: string;
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

export interface CreateBlastCampaignInput {
  session: string;
  name: string;
  message_template: string;
  recipients: string[];
  /** Step 4 (Blast <-> Office integration) — only meaningful for a
   * globally-accessing user (Superadmin/Global Admin), who must pick an
   * Office explicitly. For everyone else the backend ignores whatever is
   * sent here and forces the caller's own Office (serializers.py
   * validate()) — so this is omitted entirely for non-global users. */
  office?: number;
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

/** GET /api/offices/ — every Office, active and inactive (OfficeListCreateView). */
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

export type OfficeRole = 'global_admin' | 'office_admin' | 'operator';

export interface AdminUser {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_superuser: boolean;
  /** `null` for a Superadmin (no OfficeMembership row at all). */
  role: OfficeRole | null;
  /** `null` for a Global Admin (by design — not tied to one Office) or a Superadmin. */
  office: { id: number; name: string } | null;
  date_joined: string;
}

/** GET /api/users/ — every user visible to the caller's admin scope:
 * all of them for Superadmin/Global Admin, only the caller's own
 * Office's users for an Office Admin (UserListCreateView). */
export function getUsers() {
  return request<AdminUser[]>(`${config.djangoBaseUrl}/api/users/`, { headers: authHeader() });
}

export function getUser(id: number) {
  return request<AdminUser>(`${config.djangoBaseUrl}/api/users/${id}/`, { headers: authHeader() });
}

export interface CreateUserInput {
  username: string;
  password: string;
  first_name?: string;
  last_name?: string;
  role: OfficeRole;
  /** Required for office_admin/operator; omit (or send null) for global_admin. */
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
  /** `role` and `office` must be sent together (UserDetailView.patch) —
   * omit both to leave Office role/membership untouched. */
  role?: OfficeRole;
  office?: number | null;
}

/** PATCH /api/users/:id/ — profile fields and/or role+office. The
 * server rejects a caller targeting their own account here (403) unless
 * they are a Superadmin, and rejects an Office Admin acting outside
 * their own Office or attempting to assign global_admin (403). */
export function updateUser(id: number, patch: UpdateUserInput) {
  return request<AdminUser>(`${config.djangoBaseUrl}/api/users/${id}/`, {
    method: 'PATCH',
    body: patch,
    headers: authHeader(),
  });
}
