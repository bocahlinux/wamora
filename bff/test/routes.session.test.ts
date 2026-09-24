import type { Express } from 'express';
import jsonwebtoken from 'jsonwebtoken';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { generateTestKeyPair } from './testKeys';

const { privateKey, publicKey } = generateTestKeyPair();

vi.mock('../src/config', () => ({
  config: {
    port: 8080,
    wahaBaseUrl: 'http://waha.internal:3000',
    wahaApiKey: 'test-waha-api-key',
    wahaSessionName: 'test_session',
    corsAllowedOrigin: '',
    jwtPublicKey: publicKey,
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
    djangoInternalBaseUrl: 'http://django.internal:8000',
    internalServiceKey: 'internal-secret',
    djangoInternalTimeoutMs: 1000,
    wahaTimeoutMs: 1000,
  },
}));

function tokenWithScopes(scopes: string[]) {
  return jsonwebtoken.sign({ sub: '42', scopes }, privateKey, {
    algorithm: 'RS256',
    issuer: 'test-issuer',
    audience: 'test-audience',
    expiresIn: '1h',
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('session routes', () => {
  let app: Express;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  describe('GET /api/sessions/:session/status', () => {
    it('requires auth', async () => {
      const res = await request(app).get('/api/sessions/test_session/status');
      expect(res.status).toBe(401);
    });

    it('requires the "reading" scope', async () => {
      const res = await request(app)
        .get('/api/sessions/test_session/status')
        .set('Authorization', `Bearer ${tokenWithScopes(['sending'])}`);
      expect(res.status).toBe(403);
    });

    it('rejects a session name the BFF is not configured for', async () => {
      const res = await request(app)
        .get('/api/sessions/some-other-session/status')
        .set('Authorization', `Bearer ${tokenWithScopes(['reading'])}`);
      expect(res.status).toBe(404);
    });

    it('returns the WAHA session status on success, never the API key', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'WORKING', engine: { engine: 'GOWS' }, me: { id: 'x' } }));

      const res = await request(app)
        .get('/api/sessions/test_session/status')
        .set('Authorization', `Bearer ${tokenWithScopes(['reading'])}`);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ session: 'test_session', status: 'WORKING', engine: { engine: 'GOWS' }, me: { id: 'x' } });
      expect(JSON.stringify(res.body)).not.toContain('test-waha-api-key');
    });

    it('maps a WAHA failure to a distinct waha_unavailable error, not a generic 500', async () => {
      fetchMock.mockResolvedValue(new Response('', { status: 500 }));
      const res = await request(app)
        .get('/api/sessions/test_session/status')
        .set('Authorization', `Bearer ${tokenWithScopes(['reading'])}`);
      expect(res.status).toBe(502);
      expect(res.body.error.code).toBe('waha_unavailable');
    });
  });

  describe.each(['start', 'stop', 'restart', 'logout'] as const)('POST /api/sessions/:session/%s', (action) => {
    it('requires the "session control" scope', async () => {
      const res = await request(app)
        .post(`/api/sessions/test_session/${action}`)
        .set('Authorization', `Bearer ${tokenWithScopes(['reading'])}`);
      expect(res.status).toBe(403);
    });

    it('never claims an unconfirmed status field on success', async () => {
      fetchMock.mockResolvedValue(jsonResponse({}));
      const res = await request(app)
        .post(`/api/sessions/test_session/${action}`)
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ success: true, session: 'test_session', requestedAction: action });
      expect(res.body.status).toBeUndefined();
    });

    it('writes an audit event (best-effort) after the WAHA call resolves', async () => {
      fetchMock.mockResolvedValue(jsonResponse({}));
      await request(app)
        .post(`/api/sessions/test_session/${action}`)
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);

      const auditCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/internal/audit-events/'));
      expect(auditCall).toBeDefined();
      const [, init] = auditCall!;
      const body = JSON.parse(init.body as string);
      expect(body.action).toBe(`session.${action}`);
      expect(body.result).toBe('success');
      expect(body.actor_id).toBe(42);
    });

    it('does not fail the response when the Django audit call itself fails', async () => {
      fetchMock.mockImplementation((url: string) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.reject(new Error('django is down'));
        }
        return Promise.resolve(jsonResponse({}));
      });

      const res = await request(app)
        .post(`/api/sessions/test_session/${action}`)
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(res.status).toBe(200);
    });

    // Session Management Audit Section 5 hardening.
    it('a WAHA timeout reports outcome "unknown", never a confirmed failure', async () => {
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        // WAHA lifecycle call: simulate an abort/timeout.
        return new Promise((_resolve, reject) => {
          (init.signal as AbortSignal).addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        });
      });

      const res = await request(app)
        .post(`/api/sessions/test_session/${action}`)
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ success: false, session: 'test_session', requestedAction: action, outcome: 'unknown' });
    });
  });

  describe('duplicate-request guarding (Session Management Audit Section 5 hardening)', () => {
    it('rejects a second start request for the same session while the first is still in flight', async () => {
      let releaseWaha: (() => void) | undefined;
      let wahaCallStarted: () => void;
      const wahaCallStartedPromise = new Promise<void>((resolve) => {
        wahaCallStarted = resolve;
      });
      fetchMock.mockImplementation((url: string) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        wahaCallStarted();
        return new Promise((resolve) => {
          releaseWaha = () => resolve(jsonResponse({}));
        });
      });

      // supertest's Test object doesn't actually dispatch the request until
      // something consumes it (calls .then()/await) — chaining .then() here
      // immediately, rather than awaiting later, is what actually kicks it
      // off so it can reach the (still-pending) WAHA call below.
      const firstResponsePromise = request(app)
        .post('/api/sessions/test_session/start')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .then((res) => res);

      // Deterministically wait until the first request has actually reached
      // (and is blocked inside) the WAHA call, rather than a fixed sleep.
      await wahaCallStartedPromise;

      const secondResponse = await request(app)
        .post('/api/sessions/test_session/start')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(secondResponse.status).toBe(409);

      releaseWaha?.();
      const firstResponse = await firstResponsePromise;
      expect(firstResponse.status).toBe(200);

      const wahaCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sessions/test_session/start'));
      expect(wahaCalls).toHaveLength(1);
    });

    it('allows a new request once the first one has resolved (lock is released)', async () => {
      fetchMock.mockResolvedValue(jsonResponse({}));

      const first = await request(app)
        .post('/api/sessions/test_session/stop')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(first.status).toBe(200);

      const second = await request(app)
        .post('/api/sessions/test_session/stop')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(second.status).toBe(200);
    });
  });

  describe('GET /api/sessions/:session/qr', () => {
    it('wraps a JSON WAHA response in the minimal envelope', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ qr: 'unrelated-field-should-not-leak-structure-assumptions' }));
      const res = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(res.status).toBe(200);
      expect(res.body.session).toBe('test_session');
      expect(res.body.format).toBe('json');
      expect(res.body).not.toHaveProperty('apiKey');
    });

    it('base64-encodes a binary image response rather than corrupting it', async () => {
      const bytes = new Uint8Array([137, 80, 78, 71]);
      fetchMock.mockResolvedValue(new Response(bytes, { status: 200, headers: { 'content-type': 'image/png' } }));
      const res = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(res.status).toBe(200);
      expect(res.body.format).toBe('image');
      expect(Buffer.from(res.body.data, 'base64')).toEqual(Buffer.from(bytes));
    });

    it('maps a 404 from WAHA to a 409 conflict (not in a pairable state)', async () => {
      fetchMock.mockResolvedValue(new Response('', { status: 404 }));
      const res = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(res.status).toBe(409);
    });

    it('a WAHA timeout reports outcome "unknown", not a confirmed failure', async () => {
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        return new Promise((_resolve, reject) => {
          (init.signal as AbortSignal).addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        });
      });

      const res = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ session: 'test_session', outcome: 'unknown' });
    });

    it('does not guard against repeated requests — retry/refresh is expected UX', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ qr: 'x' }));
      const first = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      const second = await request(app)
        .get('/api/sessions/test_session/qr')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`);
      expect(first.status).toBe(200);
      expect(second.status).toBe(200);
    });
  });

  describe('POST /api/sessions/:session/pairing-code', () => {
    it('requires phoneNumber in the body', async () => {
      const res = await request(app)
        .post('/api/sessions/test_session/pairing-code')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .send({});
      expect(res.status).toBe(400);
    });

    it('returns the code in a minimal envelope', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ code: 'ABCD-1234' }));
      const res = await request(app)
        .post('/api/sessions/test_session/pairing-code')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .send({ phoneNumber: '628123456789' });
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ session: 'test_session', code: 'ABCD-1234' });
    });

    it('a WAHA timeout reports outcome "unknown", not a confirmed failure', async () => {
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        return new Promise((_resolve, reject) => {
          (init.signal as AbortSignal).addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        });
      });

      const res = await request(app)
        .post('/api/sessions/test_session/pairing-code')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .send({ phoneNumber: '628123456789' });
      expect(res.status).toBe(200);
      expect(res.body).toEqual({ session: 'test_session', outcome: 'unknown' });
    });

    it('rejects a second pairing-code request while the first is still in flight', async () => {
      let releaseWaha: (() => void) | undefined;
      let wahaCallStarted: () => void;
      const wahaCallStartedPromise = new Promise<void>((resolve) => {
        wahaCallStarted = resolve;
      });
      fetchMock.mockImplementation((url: string) => {
        if (String(url).includes('/internal/audit-events/')) {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        wahaCallStarted();
        return new Promise((resolve) => {
          releaseWaha = () => resolve(jsonResponse({ code: 'ABCD-1234' }));
        });
      });

      const firstResponsePromise = request(app)
        .post('/api/sessions/test_session/pairing-code')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .send({ phoneNumber: '628123456789' })
        .then((res) => res);

      await wahaCallStartedPromise;

      const secondResponse = await request(app)
        .post('/api/sessions/test_session/pairing-code')
        .set('Authorization', `Bearer ${tokenWithScopes(['session control'])}`)
        .send({ phoneNumber: '628123456789' });
      expect(secondResponse.status).toBe(409);

      releaseWaha?.();
      const firstResponse = await firstResponsePromise;
      expect(firstResponse.status).toBe(200);
    });
  });
});
