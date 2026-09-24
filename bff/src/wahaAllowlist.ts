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
  | 'sendText';

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
};
