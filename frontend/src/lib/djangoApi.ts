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

export interface Me {
  id: number;
  username: string;
  display_name: string;
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
}

/** GET /api/chats/ — paginated, most-recently-active chat first.
 * Requires the JWT's `reading` scope (apps.authn.permissions.HasReadingScope). */
export function getChats(page = 1) {
  return request<PaginatedResponse<ChatSummary>>(`${config.djangoBaseUrl}/api/chats/?page=${page}`, {
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
