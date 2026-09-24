import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/config', () => ({
  config: {
    djangoInternalBaseUrl: 'http://django.internal:8000',
    internalServiceKey: 'test-internal-service-key',
    djangoInternalTimeoutMs: 1000,
  },
}));

describe('logAuditFallback', () => {
  let logSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
  });

  afterEach(() => {
    logSpy.mockRestore();
  });

  it('logs a structured JSON line with the audit fields', async () => {
    const { logAuditFallback } = await import('../src/auditHelper');
    logAuditFallback({ actorId: '7', action: 'session.start', target: 'test_session', result: 'success' });

    expect(logSpy).toHaveBeenCalledTimes(1);
    const parsed = JSON.parse(logSpy.mock.calls[0][0] as string);
    expect(parsed).toMatchObject({
      type: 'audit',
      actor_id: '7',
      action: 'session.start',
      target: 'test_session',
      result: 'success',
    });
    expect(parsed.timestamp).toBeDefined();
  });

  it('never includes any credential-shaped value', async () => {
    const { logAuditFallback } = await import('../src/auditHelper');
    logAuditFallback({ action: 'session.start', target: 'test_session', result: 'success' });
    expect(logSpy.mock.calls[0][0]).not.toContain('test-internal-service-key');
  });
});

describe('recordAudit', () => {
  let logSpy: ReturnType<typeof vi.spyOn>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    logSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('emits the local fallback line AND attempts the Django write', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 201 }));
    const { recordAudit } = await import('../src/auditHelper');

    await recordAudit({ action: 'session.stop', target: 'test_session', result: 'success' });

    // Exactly one audit fallback JSON line — djangoClient.ts's own
    // diagnostic logging (docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md)
    // also logs on this same call, so this counts audit lines
    // specifically rather than asserting a total console.log count.
    const auditLines = logSpy.mock.calls.filter((call) => {
      try {
        return JSON.parse(call[0] as string).type === 'audit';
      } catch {
        return false;
      }
    });
    expect(auditLines).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/internal/audit-events/');
  });

  it('still emits the local fallback line even when the Django write fails', async () => {
    fetchMock.mockRejectedValue(new Error('django unreachable'));
    const { recordAudit } = await import('../src/auditHelper');

    await expect(
      recordAudit({ action: 'session.stop', target: 'test_session', result: 'failure' }),
    ).resolves.toBeUndefined();

    const auditLines = logSpy.mock.calls.filter((call) => {
      try {
        return JSON.parse(call[0] as string).type === 'audit';
      } catch {
        return false;
      }
    });
    expect(auditLines).toHaveLength(1);
  });
});
