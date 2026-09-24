import type { Express } from 'express';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const ALLOWED_ORIGIN = 'http://localhost:5173';

vi.mock('../src/config', () => ({
  config: {
    port: 8080,
    wahaBaseUrl: 'http://waha.internal:3000',
    wahaApiKey: 'test-waha-api-key',
    wahaSessionName: 'test_session',
    corsAllowedOrigin: ALLOWED_ORIGIN,
    jwtPublicKey: '',
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
    djangoInternalBaseUrl: '',
    internalServiceKey: '',
    djangoInternalTimeoutMs: 1000,
    wahaTimeoutMs: 1000,
  },
}));

describe('CORS', () => {
  let app: Express;

  beforeEach(async () => {
    vi.resetModules();
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  it('reflects Access-Control-Allow-Origin for the configured origin on a real request', async () => {
    const res = await request(app).get('/health').set('Origin', ALLOWED_ORIGIN);
    expect(res.headers['access-control-allow-origin']).toBe(ALLOWED_ORIGIN);
  });

  it('answers a preflight OPTIONS request for the configured origin', async () => {
    const res = await request(app)
      .options('/api/sessions/test_session/status')
      .set('Origin', ALLOWED_ORIGIN)
      .set('Access-Control-Request-Method', 'GET')
      .set('Access-Control-Request-Headers', 'authorization,content-type');

    expect(res.headers['access-control-allow-origin']).toBe(ALLOWED_ORIGIN);
    expect(res.status).toBeLessThan(400);
  });

  it('does NOT allow an unconfigured/malicious origin', async () => {
    const res = await request(app).get('/health').set('Origin', 'http://evil.example.com');
    expect(res.headers['access-control-allow-origin']).toBeUndefined();
  });

  it('does not enable credentialed CORS (Bearer-token auth needs no cookies)', async () => {
    const res = await request(app).get('/health').set('Origin', ALLOWED_ORIGIN);
    expect(res.headers['access-control-allow-credentials']).toBeUndefined();
  });

  it('never uses a wildcard origin', async () => {
    const res = await request(app).get('/health').set('Origin', ALLOWED_ORIGIN);
    expect(res.headers['access-control-allow-origin']).not.toBe('*');
  });
});

describe('CORS when unconfigured (fails closed, not permissive)', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('allows no origin at all when CORS_ALLOWED_ORIGIN is empty', async () => {
    vi.doMock('../src/config', () => ({
      config: {
        port: 8080,
        wahaBaseUrl: '',
        wahaApiKey: '',
        wahaSessionName: '',
        corsAllowedOrigin: '',
        jwtPublicKey: '',
        jwtIssuer: '',
        jwtAudience: '',
        djangoInternalBaseUrl: '',
        internalServiceKey: '',
        djangoInternalTimeoutMs: 1000,
        wahaTimeoutMs: 1000,
      },
    }));
    const { createApp } = await import('../src/app');
    const app = createApp();

    const res = await request(app).get('/health').set('Origin', 'http://localhost:5173');
    expect(res.headers['access-control-allow-origin']).toBeUndefined();
  });
});
