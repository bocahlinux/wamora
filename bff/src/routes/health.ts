// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 1/13:
// reports WAHA reachability distinctly from BFF-process health — the
// "which upstream failed" signal Phase 9's degraded-mode UI will consume.

import { Router } from 'express';

import { config } from '../config';
import { callWaha } from '../wahaClient';

const router = Router();

router.get('/health', async (_req, res) => {
  let wahaReachable = false;
  if (config.wahaBaseUrl && config.wahaApiKey && config.wahaSessionName) {
    const result = await callWaha('getSessionStatus', config.wahaSessionName, {
      baseUrl: config.wahaBaseUrl,
      apiKey: config.wahaApiKey,
      timeoutMs: config.wahaTimeoutMs,
    });
    wahaReachable = result.outcome === 'success';
  }
  res.status(200).json({ status: 'ok', service: 'bff', waha: { reachable: wahaReachable } });
});

export default router;
