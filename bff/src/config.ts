// Environment-driven configuration. Secrets (e.g. WAHA_API_KEY,
// JWT_PUBLIC_KEY, INTERNAL_SERVICE_KEY) are read here and must never be
// forwarded to the browser — see docs/06-SECURITY.md.
//
// This module only ever reads from `process.env` — it does not load
// `.env` itself. Locally, `npm run dev` loads `bff/.env` via Node's own
// `--env-file-if-exists` flag (package.json); in production,
// `infrastructure/tencent/docker-compose.yml` injects the same variables
// via `env_file:`. Both paths converge on `process.env` before this file
// ever runs, so no loader belongs here.

import fs from 'fs';

function readKey(inlineVar: string, pathVar: string): string {
  const inline = process.env[inlineVar];
  if (inline) {
    // Environment files commonly can't hold real newlines inside a value;
    // allow a literal "\n" to represent one (same convention as the
    // Django side — config/settings.py's _read_key).
    return inline.replace(/\\n/g, '\n');
  }
  const path = process.env[pathVar];
  if (path) {
    return fs.readFileSync(path, 'utf-8');
  }
  return '';
}

export const config = {
  port: Number(process.env.PORT ?? 8080),
  wahaBaseUrl: process.env.WAHA_BASE_URL ?? '',
  wahaApiKey: process.env.WAHA_API_KEY ?? '',
  corsAllowedOrigin: process.env.CORS_ALLOWED_ORIGIN ?? '',

  // docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 6:
  // the BFF is provisioned for a single WAHA session in this v1
  // implementation (this project's "1, max 2-3 sessions" scale — see
  // docs/00-MASTER-SPEC.md — doesn't yet warrant a session->key map; every
  // route validates the :session path parameter against this exact name
  // and returns 404 for anything else, rather than silently accepting an
  // arbitrary session name it holds no credential for).
  wahaSessionName: process.env.WAHA_SESSION_NAME ?? '',

  // JWT verification (contract Section 4) — the BFF holds only the public
  // key, verifies locally, no live Django call per request.
  jwtPublicKey: readKey('JWT_PUBLIC_KEY', 'JWT_PUBLIC_KEY_PATH'),
  jwtIssuer: process.env.JWT_ISSUER ?? 'waha-monitoring-django',
  jwtAudience: process.env.JWT_AUDIENCE ?? 'waha-monitoring-bff',

  // BFF -> Django internal endpoints (contract Section 8).
  djangoInternalBaseUrl: process.env.DJANGO_INTERNAL_BASE_URL ?? '',
  internalServiceKey: process.env.INTERNAL_SERVICE_KEY ?? '',
  // Milliseconds — approved default 2s (contract Section 8).
  djangoInternalTimeoutMs: Number(process.env.DJANGO_INTERNAL_TIMEOUT_MS ?? 2000),

  // Milliseconds — bounded timeout for the BFF's own calls to WAHA. Not
  // specified by any doc; chosen conservatively (WAHA's own QR probe was
  // observed hanging in prior live-verification rounds — see
  // docs/generated/PHASE-6-BLOCKER-RESOLUTION.md).
  wahaTimeoutMs: Number(process.env.WAHA_TIMEOUT_MS ?? 10000),

  // Office/Celery -> Tencent/BFF internal dispatch endpoint (Phase 11 —
  // Blast). A NEW, distinct shared secret from internalServiceKey above
  // (that one authenticates the OPPOSITE direction, BFF -> Django) —
  // authenticates the Office-side Celery worker for exactly one narrow,
  // allowlisted route (routes/internalBlast.ts). Never accepted from a
  // browser/frontend JWT. Must match OFFICE_DISPATCH_SERVICE_KEY on the
  // backend/.env side.
  officeDispatchServiceKey: process.env.OFFICE_DISPATCH_SERVICE_KEY ?? '',
};
