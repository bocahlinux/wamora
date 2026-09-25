import cors from 'cors';
import express from 'express';

import { config } from './config';
import { buildCorsOptions } from './corsOptions';
import healthRouter from './routes/health';
import internalBlastRouter from './routes/internalBlast';
import messagesRouter from './routes/messages';
import sessionRouter from './routes/session';

export function createApp() {
  const app = express();
  // Must run before the route handlers so preflight OPTIONS requests are
  // answered with the right headers (docs/generated/PHASE-7-CORS-FIX-REPORT.md)
  // — this is what was missing: CORS_ALLOWED_ORIGIN existed in config
  // since Phase 0 but was never applied to any middleware.
  app.use(cors(buildCorsOptions(config.corsAllowedOrigin)));
  app.use(express.json());

  app.use(healthRouter);
  app.use('/api', sessionRouter);
  app.use('/api', messagesRouter);
  // Office/Celery -> BFF internal dispatch (Phase 11 — Blast). Deliberately
  // NOT under /api (the prefix every frontend-reachable route uses) and
  // gated by requireOfficeDispatchKey only, never requireAuth/requireScope
  // — see routes/internalBlast.ts's own docstring.
  app.use('/internal', internalBlastRouter);

  return app;
}
