import { afterEach, describe, expect, it, vi } from 'vitest';

import { callWaha } from '../src/wahaClient';

const baseOptions = { baseUrl: 'http://waha.internal:3000', apiKey: 'test-key', timeoutMs: 1000 };

afterEach(() => {
  vi.restoreAllMocks();
});

describe('callWaha', () => {
  it('sends the API key header and never the credential in a query param', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'WORKING' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await callWaha('getSessionStatus', 'test_session', baseOptions);

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).not.toContain('test-key');
    expect((init.headers as Record<string, string>)['X-Api-Key']).toBe('test-key');
  });

  it('only ever calls one of the allowlisted paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await callWaha('startSession', 'test_session', baseOptions);
    const [url] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe('/api/sessions/test_session/start');
  });

  it('returns outcome "success" and parsed json for a 200 JSON response', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ status: 'WORKING' }), { status: 200, headers: { 'content-type': 'application/json' } }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await callWaha('getSessionStatus', 'test_session', baseOptions);
    expect(result.outcome).toBe('success');
    expect(result.json).toEqual({ status: 'WORKING' });
  });

  it('returns outcome "http_error" for a non-2xx response, without throwing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('bad request', { status: 400 }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await callWaha('sendText', 'test_session', baseOptions);
    expect(result.outcome).toBe('http_error');
    expect(result.status).toBe(400);
  });

  it('returns outcome "network_error" when fetch rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('ECONNREFUSED')),
    );

    const result = await callWaha('getSessionStatus', 'test_session', baseOptions);
    expect(result.outcome).toBe('network_error');
  });

  it('returns outcome "timeout" when the request exceeds timeoutMs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((_url: string, init: { signal: AbortSignal }) => {
        return new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        });
      }),
    );

    const result = await callWaha('getSessionStatus', 'test_session', { ...baseOptions, timeoutMs: 10 });
    expect(result.outcome).toBe('timeout');
  });

  it('base64-encodes binary-ish bodies so they survive intact', async () => {
    const bytes = new Uint8Array([0, 1, 2, 255, 254]);
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(bytes, { status: 200, headers: { 'content-type': 'image/png' } }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await callWaha('getQr', 'test_session', baseOptions);
    expect(result.outcome).toBe('success');
    expect(Buffer.from(result.bodyBase64 ?? '', 'base64')).toEqual(Buffer.from(bytes));
  });
});
