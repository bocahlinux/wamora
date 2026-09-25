// Phase 12 (Security hardening) MUST-FIX #5 — bff/src/middleware/rateLimit.ts.
import type { Express } from 'express';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const SMALL_LIMIT = 3;

vi.mock('../src/config', () => ({
  config: {
    port: 8080,
    wahaBaseUrl: 'http://waha.internal:3000',
    wahaApiKey: 'test-waha-api-key',
    wahaSessionName: 'test_session',
    corsAllowedOrigin: '',
    jwtPublicKey: '',
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
    djangoInternalBaseUrl: '',
    internalServiceKey: '',
    djangoInternalTimeoutMs: 1000,
    wahaTimeoutMs: 1000,
    // Deliberately tiny so tests can exhaust it in a handful of requests
    // rather than the real 300/minute production default.
    rateLimitMaxPerMinute: SMALL_LIMIT,
  },
}));

describe('/api rate limiting', () => {
  let app: Express;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  it('allows requests up to the configured limit', async () => {
    for (let i = 0; i < SMALL_LIMIT; i++) {
      const res = await request(app).get('/api/sessions/test_session/status');
      // No Authorization header — 401 from requireAuth, but NOT 429; the
      // limiter itself must not be what's rejecting these first N requests.
      expect(res.status).toBe(401);
    }
  });

  it('returns 429 once the limit is exceeded within the window', async () => {
    for (let i = 0; i < SMALL_LIMIT; i++) {
      await request(app).get('/api/sessions/test_session/status');
    }
    const res = await request(app).get('/api/sessions/test_session/status');
    expect(res.status).toBe(429);
    expect(res.body).toEqual({
      error: {
        code: 'rate_limited',
        message: 'Too many requests — please slow down and try again shortly.',
      },
    });
  });

  it('applies across different /api routes sharing the same limiter, not per-route', async () => {
    await request(app).get('/api/sessions/test_session/status');
    await request(app).get('/api/sessions/test_session/status');
    await request(app).post('/api/sessions/test_session/messages');
    const res = await request(app).get('/api/sessions/test_session/status');
    expect(res.status).toBe(429);
  });

  it('never blocks /health', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } }),
    );
    for (let i = 0; i < SMALL_LIMIT + 2; i++) {
      const res = await request(app).get('/health');
      expect(res.status).toBe(200);
    }
  });

  it('never blocks /internal (shared-secret-gated, not part of this rate limit)', async () => {
    for (let i = 0; i < SMALL_LIMIT + 2; i++) {
      const res = await request(app).post('/internal/blast/send');
      expect(res.status).not.toBe(429);
    }
  });
});
