// Generic HTTP client used by both the BFF and Django clients. Categorizes
// every outcome into exactly the states docs/generated/PHASE-7 (task
// Section 14) requires the UI to distinguish: validation error,
// unauthorized, forbidden, not found, server error, network failure,
// timeout, or an unrecognized/unknown response — never a bare, uncategorized
// throw that a page would have to guess about.

export type ApiError =
  | { kind: 'validation'; message: string }
  | { kind: 'unauthorized' }
  | { kind: 'forbidden' }
  | { kind: 'not_found' }
  | { kind: 'server_error'; status: number }
  | { kind: 'network_error' }
  | { kind: 'timeout' }
  | { kind: 'unknown'; status?: number };

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

const DEFAULT_TIMEOUT_MS = 10000;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
}

function errorForStatus(status: number, body: unknown): ApiError {
  if (status === 401) return { kind: 'unauthorized' };
  if (status === 403) return { kind: 'forbidden' };
  if (status === 404) return { kind: 'not_found' };
  if (status === 400 || status === 409) {
    const message =
      (body && typeof body === 'object' && 'error' in body && typeof (body as Record<string, unknown>).error === 'object'
        ? ((body as Record<string, unknown>).error as Record<string, unknown>).message
        : undefined) ?? 'The request could not be processed.';
    return { kind: 'validation', message: String(message) };
  }
  if (status >= 500) return { kind: 'server_error', status };
  return { kind: 'unknown', status };
}

export async function request<T>(url: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: {
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    let parsed: unknown = undefined;
    const text = await response.text();
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        // Non-JSON body — kept undefined; treated as unknown-shape below
        // for a non-2xx response, or as an unexpected-empty success below.
      }
    }

    if (!response.ok) {
      return { ok: false, error: errorForStatus(response.status, parsed) };
    }
    if (parsed === undefined) {
      // Empty or non-JSON body on a 2xx — an unexpected response shape,
      // not assumed to be a usable T.
      return { ok: false, error: { kind: 'unknown', status: response.status } };
    }
    return { ok: true, data: parsed as T };
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return { ok: false, error: { kind: 'timeout' } };
    }
    return { ok: false, error: { kind: 'network_error' } };
  } finally {
    clearTimeout(timer);
  }
}

/** A short, operator-appropriate message for each error kind — never a raw
 * server response or stack trace (task Section 14: "Do not display raw
 * server stack traces or sensitive backend responses to users"). */
export function describeError(error: ApiError): string {
  switch (error.kind) {
    case 'validation':
      return error.message;
    case 'unauthorized':
      return 'Your session has expired. Please sign in again.';
    case 'forbidden':
      return "You don't have permission to do this.";
    case 'not_found':
      return 'Not found.';
    case 'server_error':
      return 'The server encountered a problem. Please try again shortly.';
    case 'network_error':
      return 'Could not reach the server. Check your connection.';
    case 'timeout':
      return 'The request took too long and was cancelled.';
    case 'unknown':
      return 'An unexpected response was received.';
  }
}
