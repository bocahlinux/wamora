import type { Request, Response } from 'express';

import { config } from '../config';
import { sendNotFound } from '../errors';

/** docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 6: this
 * v1 BFF is provisioned for exactly one WAHA session (WAHA_SESSION_NAME).
 * Any other :session path parameter is rejected — the BFF holds no
 * credential for it, so silently accepting it would be worse than a clear
 * 404. */
export function validateSession(req: Request, res: Response): boolean {
  const requested = req.params.session;
  if (!config.wahaSessionName || requested !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return false;
  }
  return true;
}
