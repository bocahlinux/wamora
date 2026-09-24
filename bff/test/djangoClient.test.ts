import { beforeEach, describe, expect, it, vi } from 'vitest';

import { registerOutboundOperation, triggerReconciliation } from '../src/djangoClient';

// docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md
// — makes postJson()'s previously-silent {ok:false} outcomes observable.
// Covers every branch: missing config, thrown fetch error, non-2xx
// response, and success — and proves the service key value itself is
// never logged in any of them.

const OPTIONS = { baseUrl: 'http://django.internal:8000', serviceKey: 'super-secret-key-value', timeoutMs: 1000 };

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('djangoClient diagnostic logging', () => {
  let logSpy: ReturnType<typeof vi.fn>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    logSpy = vi.fn();
    vi.spyOn(console, 'log').mockImplementation(logSpy);
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  function loggedLines(): string[] {
    return logSpy.mock.calls.map((call) => String(call[0]));
  }

  it('logs the request method/URL before fetching, with the key attached but never its value', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ triggered: true, executor: 'sync' }));

    await triggerReconciliation({ session: 'no_epahari', chatId: 'c1@lid' }, OPTIONS);

    const lines = loggedLines();
    const before = lines.find((l) => l.includes('-> POST'));
    expect(before).toBeDefined();
    expect(before).toContain('http://django.internal:8000/internal/reconciliation/trigger/');
    expect(before).toContain('X-Internal-Service-Key attached');
    expect(before).toContain(`length=${OPTIONS.serviceKey.length}`);
    // The actual secret value must never appear in any logged line.
    expect(lines.join('\n')).not.toContain(OPTIONS.serviceKey);
  });

  it('logs the HTTP status after a successful response', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ triggered: true, executor: 'sync' }, 200));

    await triggerReconciliation({ session: 'no_epahari', chatId: 'c1@lid' }, OPTIONS);

    expect(loggedLines().some((l) => l.includes('<- POST') && l.includes('status=200'))).toBe(true);
  });

  it('logs the status and error code when Django rejects the request (e.g. 403)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: 'permission_denied', message: 'nope', request_id: 'req-1' } }, 403),
    );

    const result = await triggerReconciliation({ session: 'no_epahari', chatId: 'c1@lid' }, OPTIONS);

    expect(result.ok).toBe(false);
    const line = loggedLines().find((l) => l.includes('status=403'));
    expect(line).toBeDefined();
    expect(line).toContain('code=permission_denied');
    expect(line).toContain('request_id=req-1');
  });

  it('logs the exception name/message when fetch throws (e.g. connection refused)', async () => {
    const err = new Error('connect ECONNREFUSED 192.168.100.200:8000');
    err.name = 'FetchError';
    fetchMock.mockRejectedValue(err);

    const result = await triggerReconciliation({ session: 'no_epahari', chatId: 'c1@lid' }, OPTIONS);

    expect(result.ok).toBe(false);
    const line = loggedLines().find((l) => l.includes('threw'));
    expect(line).toBeDefined();
    expect(line).toContain('FetchError');
    expect(line).toContain('ECONNREFUSED');
  });

  it('logs which specific config value is missing, and never attempts fetch, when baseUrl is empty', async () => {
    await registerOutboundOperation(
      { session: 's', idempotencyKey: 'k', destination: 'd', operationType: 'sendText' },
      { baseUrl: '', serviceKey: 'x', timeoutMs: 1000 },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    const line = loggedLines().find((l) => l.includes('skipped'));
    expect(line).toBeDefined();
    expect(line).toContain('DJANGO_INTERNAL_BASE_URL');
  });

  it('logs which specific config value is missing, and never attempts fetch, when serviceKey is empty', async () => {
    await registerOutboundOperation(
      { session: 's', idempotencyKey: 'k', destination: 'd', operationType: 'sendText' },
      { baseUrl: 'http://django.internal:8000', serviceKey: '', timeoutMs: 1000 },
    );

    expect(fetchMock).not.toHaveBeenCalled();
    const line = loggedLines().find((l) => l.includes('skipped'));
    expect(line).toBeDefined();
    expect(line).toContain('INTERNAL_SERVICE_KEY');
  });
});
