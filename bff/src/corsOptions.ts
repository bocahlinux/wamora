// docs/generated/PHASE-7-CORS-FIX-REPORT.md: the BFF already had a
// CORS_ALLOWED_ORIGIN config value (Phase 0 scaffold) that was never
// actually wired into any CORS middleware — this closes that gap.
// Comma-separated for forward compatibility (multiple deployment
// origins), even though the variable name is singular for historical
// reasons. Never a wildcard: an unconfigured value means no origin is
// permitted (fails closed), not "allow everything."

import type { CorsOptions } from 'cors';

export function buildCorsOptions(corsAllowedOrigin: string): CorsOptions {
  const origins = corsAllowedOrigin
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean);

  return {
    // No credentials needed: auth is a Bearer token in an Authorization
    // header, never a cookie — the frontend's fetch() calls never set
    // `credentials: 'include'`. Leaving this false (the `cors` package's
    // own default) is the least-privilege choice, not an oversight.
    credentials: false,
    origin: origins.length > 0 ? origins : false,
  };
}
