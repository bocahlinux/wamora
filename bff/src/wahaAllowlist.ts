// The BFF is not a generic proxy: it must only ever call a fixed, explicit
// set of WAHA endpoints (see docs/01-ARCHITECTURE.md, docs/06-SECURITY.md,
// docs/CLAUDE.md rule 5). This module is the single place that allowlist
// lives — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 2's
// route table, restated as code.
//
// Enforcement is structural, not just a runtime string check: wahaClient's
// callWaha() only accepts one of the named keys below, so it is not
// possible to construct an arbitrary WAHA path from a route handler even
// by mistake — the allowlist IS the set of paths that can be built.

export type WahaEndpointName =
  | 'getSessionStatus'
  | 'startSession'
  | 'stopSession'
  | 'restartSession'
  | 'logoutSession'
  | 'getQr'
  | 'requestPairingCode'
  | 'sendText'
  | 'sendList'
  | 'startTyping'
  | 'stopTyping'
  | 'checkNumberExists';

interface WahaEndpointDef {
  method: 'GET' | 'POST';
  path: (session: string) => string;
}

const enc = (s: string): string => encodeURIComponent(s);

export const WAHA_ALLOWED_ENDPOINTS: Record<WahaEndpointName, WahaEndpointDef> = {
  getSessionStatus: { method: 'GET', path: (s) => `/api/sessions/${enc(s)}` },
  startSession: { method: 'POST', path: (s) => `/api/sessions/${enc(s)}/start` },
  stopSession: { method: 'POST', path: (s) => `/api/sessions/${enc(s)}/stop` },
  restartSession: { method: 'POST', path: (s) => `/api/sessions/${enc(s)}/restart` },
  logoutSession: { method: 'POST', path: (s) => `/api/sessions/${enc(s)}/logout` },
  getQr: { method: 'GET', path: (s) => `/api/${enc(s)}/auth/qr` },
  requestPairingCode: { method: 'POST', path: (s) => `/api/${enc(s)}/auth/request-code` },
  sendText: { method: 'POST', path: () => '/api/sendText' },
  // Discussed requirement — Conversation/Bot Engine interactive list
  // menus. Live-verified by the project operator directly against this
  // exact WAHA deployment (GOWS engine) before this endpoint was added
  // to the allowlist — never assumed from WAHA's general documentation
  // alone (this project's standing evidence-based rule).
  sendList: { method: 'POST', path: () => '/api/sendList' },
  // Discussed requirement — human-like reply delay (bot auto-reply) and
  // the Inbox composer's own typing indicator. Request shape given
  // directly by the project operator's own curl examples: POST with
  // `{chatId, session}`, no session in the path — same "session lives in
  // the body, not the URL" shape `sendText`/`sendList` already use.
  startTyping: { method: 'POST', path: () => '/api/startTyping' },
  stopTyping: { method: 'POST', path: () => '/api/stopTyping' },
  // Blast number-validity check (Discussed requirement) — live-verified
  // directly against the real WAHA deployment: `phone`/`session` as query
  // params, response `{numberExists, chatId, pn}`. Not a documentation
  // guess (this project's standing evidence-based rule for every WAHA
  // endpoint added to this allowlist).
  checkNumberExists: { method: 'GET', path: () => '/api/contacts/check-exists' },
};
