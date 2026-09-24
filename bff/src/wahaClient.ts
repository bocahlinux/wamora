// WAHA HTTP client — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
// Section 6. Only ever calls a WAHA_ALLOWED_ENDPOINTS member (CLAUDE.md
// rule 5). Uses Node's built-in fetch (Node 22) — no new HTTP-client
// dependency needed. Never logs or returns the API key.

import { WAHA_ALLOWED_ENDPOINTS, type WahaEndpointName } from './wahaAllowlist';

export interface WahaCallResult {
  outcome: 'success' | 'http_error' | 'timeout' | 'network_error';
  status?: number;
  contentType?: string;
  /** utf-8 decode of the body — safe for JSON/text, may be unusable
   * (mojibake) for genuinely binary content; use bodyBase64 for that. */
  bodyText?: string;
  /** base64 of the raw response bytes — always safe, use for binary
   * content (e.g. an image/* QR response). */
  bodyBase64?: string;
  json?: unknown;
}

export interface WahaCallOptions {
  baseUrl: string;
  apiKey: string;
  timeoutMs: number;
  body?: unknown;
  query?: Record<string, string>;
}

export async function callWaha(
  endpointName: WahaEndpointName,
  session: string,
  options: WahaCallOptions,
): Promise<WahaCallResult> {
  const endpoint = WAHA_ALLOWED_ENDPOINTS[endpointName];
  const url = new URL(endpoint.path(session), options.baseUrl);
  if (options.query) {
    for (const [key, value] of Object.entries(options.query)) {
      url.searchParams.set(key, value);
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs);

  try {
    const response = await fetch(url, {
      method: endpoint.method,
      headers: {
        'X-Api-Key': options.apiKey,
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    const contentType = response.headers.get('content-type') ?? undefined;
    const buffer = Buffer.from(await response.arrayBuffer());
    const bodyBase64 = buffer.toString('base64');
    const bodyText = buffer.toString('utf-8');
    let json: unknown;
    if (contentType?.includes('application/json') && bodyText) {
      try {
        json = JSON.parse(bodyText);
      } catch {
        json = undefined;
      }
    }

    return {
      outcome: response.ok ? 'success' : 'http_error',
      status: response.status,
      contentType,
      bodyText,
      bodyBase64,
      json,
    };
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') {
      return { outcome: 'timeout' };
    }
    return { outcome: 'network_error' };
  } finally {
    clearTimeout(timer);
  }
}
