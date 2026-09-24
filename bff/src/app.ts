import cors from 'cors';
import express from 'express';

import { config } from './config';
import { buildCorsOptions } from './corsOptions';
import healthRouter from './routes/health';
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

  return app;
}
