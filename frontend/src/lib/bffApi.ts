import { authHeader } from './auth';
import { config } from './config';
import { request } from './api';

export interface BffHealth {
  status: string;
  service: string;
  waha: { reachable: boolean };
}

/** GET /health — no auth (docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
 * Section 2). Reports WAHA reachability distinctly from the BFF process
 * itself, per the contract's degraded-mode requirement. */
export function getBffHealth() {
  return request<BffHealth>(`${config.bffBaseUrl}/health`);
}

export interface SessionStatus {
  session: string;
  status?: string;
  engine?: unknown;
  me?: unknown;
}

/** GET /api/sessions/:session/status — requires the `reading` scope
 * (contract Section 2/5). Read-only. */
export function getSessionStatus(session: string) {
  return request<SessionStatus>(`${config.bffBaseUrl}/api/sessions/${encodeURIComponent(session)}/status`, {
    headers: authHeader(),
  });
}

// Session lifecycle/QR/pairing — Session Management phase
// (docs/generated/SESSION-MANAGEMENT-IMPLEMENTATION-REPORT.md). All
// require the `session control` scope. `outcome: 'unknown'` on a 200
// response means the BFF's WAHA call timed out/failed to connect — the
// action may or may not have actually applied server-side; it is
// deliberately not reported as a confirmed success or failure (see the
// BFF hardening in the same report).
export type SessionLifecycleAction = 'start' | 'stop' | 'restart' | 'logout';

export interface SessionActionResult {
  success: boolean;
  session: string;
  requestedAction: SessionLifecycleAction;
  outcome?: 'unknown';
}

function sessionAction(session: string, action: SessionLifecycleAction) {
  return request<SessionActionResult>(`${config.bffBaseUrl}/api/sessions/${encodeURIComponent(session)}/${action}`, {
    method: 'POST',
    headers: authHeader(),
  });
}

export const startSession = (session: string) => sessionAction(session, 'start');
export const stopSession = (session: string) => sessionAction(session, 'stop');
export const restartSession = (session: string) => sessionAction(session, 'restart');
export const logoutSession = (session: string) => sessionAction(session, 'logout');

export interface SessionQrResult {
  session: string;
  /** 'image': `data` is base64-encoded image bytes, render directly.
   * 'json': `data` is WAHA's raw, field-level-undocumented JSON — shown
   * as-is, never guessed at (bff/src/routes/session.ts's own comment:
   * "WAHA's exact QR response shape is undocumented at the field
   * level"). 'raw': `data` is base64 of an unrecognized content type. */
  format?: 'json' | 'image' | 'raw';
  data?: unknown;
  outcome?: 'unknown';
}

/** GET /api/sessions/:session/qr. A 409 (session not awaiting pairing) or
 * any other error surfaces through the normal ApiError path. */
export function getSessionQr(session: string) {
  return request<SessionQrResult>(`${config.bffBaseUrl}/api/sessions/${encodeURIComponent(session)}/qr`, {
    headers: authHeader(),
  });
}

export interface SessionPairingCodeResult {
  session: string;
  code?: string;
  outcome?: 'unknown';
}

/** POST /api/sessions/:session/pairing-code. */
export function requestPairingCode(session: string, phoneNumber: string) {
  return request<SessionPairingCodeResult>(
    `${config.bffBaseUrl}/api/sessions/${encodeURIComponent(session)}/pairing-code`,
    { method: 'POST', body: { phoneNumber }, headers: authHeader() },
  );
}

// Inbox composer (canonical Phase 8) —
// docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 6/11: reuses this
// existing, already-tested, idempotent send endpoint exactly as-is — the
// composer must never call WAHA directly and must not duplicate this
// idempotency logic. `outcome: undefined` + `status: 'sent'` is a
// confirmed success; `status: 'unknown'` is the same ambiguous-timeout
// case already handled elsewhere in this app; a confirmed failure (a
// non-2xx WAHA response) surfaces through the normal ApiError path
// (502 waha_unavailable), same as every other BFF call.
export interface SendMessageResult {
  status: 'sent' | 'pending' | 'unknown';
  providerMessageId?: string;
}

/** POST /api/sessions/:session/messages. Requires the `sending` scope
 * and a per-attempt `Idempotency-Key` (contract Section 9) — the caller
 * decides the key so a genuine retry of the same logical send can reuse
 * it; a new user-initiated send always gets a fresh one. */
export function sendMessage(session: string, chatId: string, text: string, idempotencyKey: string) {
  return request<SendMessageResult>(`${config.bffBaseUrl}/api/sessions/${encodeURIComponent(session)}/messages`, {
    method: 'POST',
    body: { chatId, text },
    headers: { ...authHeader(), 'Idempotency-Key': idempotencyKey },
  });
}
