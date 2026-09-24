// Consistent error envelope — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
// Section 13. Every error response identifies *which* upstream failed
// (auth check vs. WAHA vs. Django), never echoes raw upstream error text
// or any credential (docs/06-SECURITY.md).

import type { Response } from 'express';

export interface ErrorBody {
  error: { code: string; message: string };
}

function send(res: Response, httpStatus: number, code: string, message: string): void {
  const body: ErrorBody = { error: { code, message } };
  res.status(httpStatus).json(body);
}

export const sendUnauthorized = (res: Response, message = 'Missing or invalid token'): void =>
  send(res, 401, 'unauthorized', message);

export const sendForbidden = (res: Response, message = 'Missing required scope'): void =>
  send(res, 403, 'forbidden', message);

export const sendNotFound = (res: Response, message = 'Not found'): void => send(res, 404, 'not_found', message);

export const sendBadRequest = (res: Response, message: string): void => send(res, 400, 'invalid_request', message);

export const sendConflict = (res: Response, message: string): void => send(res, 409, 'conflict', message);

export const sendWahaUnavailable = (res: Response): void =>
  send(res, 502, 'waha_unavailable', 'WAHA is unreachable or returned an unexpected response');
