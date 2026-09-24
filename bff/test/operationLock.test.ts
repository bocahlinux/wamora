import { describe, expect, it } from 'vitest';

import { acquireOperationLock, releaseOperationLock } from '../src/operationLock';

describe('operationLock', () => {
  it('acquires a free key', () => {
    expect(acquireOperationLock('a:start')).toBe(true);
    releaseOperationLock('a:start');
  });

  it('refuses to acquire an already-held key', () => {
    expect(acquireOperationLock('b:start')).toBe(true);
    expect(acquireOperationLock('b:start')).toBe(false);
    releaseOperationLock('b:start');
  });

  it('allows re-acquiring after release', () => {
    expect(acquireOperationLock('c:start')).toBe(true);
    releaseOperationLock('c:start');
    expect(acquireOperationLock('c:start')).toBe(true);
    releaseOperationLock('c:start');
  });

  it('keeps distinct keys independent', () => {
    expect(acquireOperationLock('d:start')).toBe(true);
    expect(acquireOperationLock('d:stop')).toBe(true);
    releaseOperationLock('d:start');
    releaseOperationLock('d:stop');
  });

  it('releasing a key that was never held is a safe no-op', () => {
    expect(() => releaseOperationLock('never-held')).not.toThrow();
  });
});
