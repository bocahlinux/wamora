// Authentication for Office/Celery -> BFF internal dispatch calls (Phase
// 11 — Blast, finalized decision 1). A NEW, distinct shared secret from
// INTERNAL_SERVICE_KEY (bff/src/djangoClient.ts's own direction, BFF ->
// Django) — this authenticates the OPPOSITE direction, the Office-side
// Celery worker calling INTO the BFF. Mirrors
// backend/apps/core/internal_auth.py's HasInternalServiceKey exactly:
// fails closed if unconfigured, constant-time comparison, never a
// session/user JWT.

import crypto from 'crypto';
import type { NextFunction, Request, Response } from 'express';

import { config } from '../config';
import { sendUnauthorized } from '../errors';

const HEADER_NAME = 'x-office-dispatch-key';

function timingSafeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) {
    // Still run a comparison of equal-length buffers so this branch does
    // not short-circuit on length alone in an observably different way
    // than a real crypto.timingSafeEqual call would for the common case.
    crypto.timingSafeEqual(bufA, bufA);
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}

/** Fails closed: if OFFICE_DISPATCH_SERVICE_KEY is unconfigured, no
 * request is ever authorized (an empty configured secret would otherwise
 * make an empty header "valid"). */
export function requireOfficeDispatchKey(req: Request, res: Response, next: NextFunction): void {
  const configured = config.officeDispatchServiceKey;
  if (!configured) {
    sendUnauthorized(res, 'Office dispatch is not configured');
    return;
  }
  const provided = req.header(HEADER_NAME) ?? '';
  if (!provided || !timingSafeEqual(provided, configured)) {
    sendUnauthorized(res);
    return;
  }
  next();
}
