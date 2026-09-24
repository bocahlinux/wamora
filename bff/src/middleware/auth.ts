// Authentication/authorization middleware —
// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Sections 4/5.

import type { NextFunction, Request, Response } from 'express';

import { config } from '../config';
import { sendForbidden, sendUnauthorized } from '../errors';
import { JwtVerificationError, verifyToken, type JwtClaims } from '../jwt';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      auth?: JwtClaims;
    }
  }
}

export function requireAuth(req: Request, res: Response, next: NextFunction): void {
  const header = req.header('Authorization') ?? '';
  const match = /^Bearer\s+(.+)$/.exec(header);
  if (!match) {
    sendUnauthorized(res, 'Missing Authorization: Bearer <token> header');
    return;
  }
  try {
    req.auth = verifyToken(match[1], {
      publicKey: config.jwtPublicKey,
      issuer: config.jwtIssuer,
      audience: config.jwtAudience,
    });
  } catch (err) {
    if (err instanceof JwtVerificationError) {
      sendUnauthorized(res);
      return;
    }
    throw err;
  }
  next();
}

export function requireScope(scope: string) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!req.auth) {
      // Programming error if reached without requireAuth first — fail
      // closed rather than assume unauthenticated == authorized.
      sendUnauthorized(res);
      return;
    }
    if (!req.auth.scopes.includes(scope)) {
      sendForbidden(res, `Missing required scope: ${scope}`);
      return;
    }
    next();
  };
}
