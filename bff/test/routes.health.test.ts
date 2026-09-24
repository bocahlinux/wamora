import type { Express } from 'express';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  },
}));

describe('GET /health', () => {
  let app: Express;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  it('requires no authentication', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } }));
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
  });

  it('reports waha.reachable=true distinctly from BFF process health when WAHA is up', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } }));
    const res = await request(app).get('/health');
    expect(res.body).toEqual({ status: 'ok', service: 'bff', waha: { reachable: true } });
  });

  it('reports waha.reachable=false when WAHA is unreachable, while the BFF itself still responds 200', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('ok');
    expect(res.body.waha.reachable).toBe(false);
  });

  it('never includes the WAHA API key in the response', async () => {
    fetchMock.mockRejectedValue(new Error('down'));
    const res = await request(app).get('/health');
    expect(JSON.stringify(res.body)).not.toContain('test-waha-api-key');
  });
});
