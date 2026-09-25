// Phase 12 (Security hardening) MUST-FIX #5 —
// docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md Section
// 3.5: the BFF previously had zero rate limiting on any route
// (bff/package.json had no express-rate-limit or equivalent, and
// bff/src/app.ts mounted no such middleware).
//
// Applied (app.ts) to the frontend-JWT-gated `/api` routes only
// (routes/session.ts, routes/messages.ts) — deliberately NOT to
// `/internal/blast/send` (routes/internalBlast.ts), which is already
// shared-secret-gated, internal-only (Office/Celery -> BFF, never a
// browser), and has its own separate, already-audited domain-specific
// dispatch throttling (apps/blast — out of this task's scope, per its own
// instructions not to touch Blast internals); and NOT to `/health` (an
// unauthenticated liveness probe with no WAHA-call surface, no side
// effects, and no credential-guessing/abuse concern of its own).
//
// In-memory store — express-rate-limit's own default. This project runs
// exactly one BFF process per deployment
// (docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md; no horizontal BFF scaling), so a
// shared/Redis-backed store is not required for this limiter to work
// correctly, and adding one would be new infrastructure this task's own
// instructions say to avoid where the standard tooling already covers the
// need.

import rateLimit from 'express-rate-limit';
import type { NextFunction, Request, Response } from 'express';

import { config } from '../config';

const WINDOW_MS = 60_000;
const DEFAULT_MAX_PER_WINDOW = 300;

export function createApiRateLimiter() {
  return rateLimit({
    windowMs: WINDOW_MS,
    limit: config.rateLimitMaxPerMinute ?? DEFAULT_MAX_PER_WINDOW,
    standardHeaders: true,
    legacyHeaders: false,
    // Matches this project's own consistent error envelope
    // (errors.ts's `send()`) rather than express-rate-limit's own default
    // plain-text body.
    handler: (_req: Request, res: Response, _next: NextFunction) => {
      res.status(429).json({
        error: {
          code: 'rate_limited',
          message: 'Too many requests — please slow down and try again shortly.',
        },
      });
    },
  });
}
