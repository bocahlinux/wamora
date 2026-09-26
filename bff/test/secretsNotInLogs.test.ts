// Phase 13 (Failure/security testing) Track A, scope item 4 — the BFF
// half of the secrets-absent-from-logs check. Mirrors
// backend/apps/core/test_secrets_not_in_logs.py's approach and rationale
// (see that file's own docstring): walk every non-test .ts file under
// bff/src, find every console.<method>(...) call site, and assert none
// of this project's known secret-bearing config fields is referenced
// inside it.
//
// This project has no TypeScript AST parser dependency today (only
// `typescript` itself as a devDependency for `tsc`, not exposed as a
// usable parser API import here without extra wiring) and per this
// task's own scope boundary ("do not add heavyweight new dependencies"),
// this uses a small hand-written, string/template-literal-aware
// bracket-depth scanner instead of a real AST — good enough to capture a
// whole (possibly multi-line) console.log(...) call as one unit, which a
// naive single-line grep would not reliably do.
import fs from 'fs';
import path from 'path';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = path.resolve(__dirname, '..', 'src');

// bff/src/config.ts's own field names for this project's secret-bearing
// values (see that file — jwtPublicKey is deliberately excluded, it's
// public by design), plus the raw env var names in case a call site
// reads process.env directly instead of via `config`.
const SECRET_TOKENS = [
  'wahaApiKey',
  'WAHA_API_KEY',
  'internalServiceKey',
  'INTERNAL_SERVICE_KEY',
  'officeDispatchServiceKey',
  'OFFICE_DISPATCH_SERVICE_KEY',
  'jwtPrivateKey',
  'JWT_PRIVATE_KEY',
];

const CONSOLE_CALL_RE = /console\s*\.\s*(log|error|warn|info|debug)\s*\(/g;

function listTsFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '__pycache__') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...listTsFiles(full));
    } else if (entry.isFile() && full.endsWith('.ts') && !full.endsWith('.test.ts')) {
      out.push(full);
    }
  }
  return out;
}

/** Given source text and the index of the `(` that opens a call, returns
 * the full call's argument text up to (not including) the matching
 * closing `)`. String/template literals are tracked so a `)` inside a
 * string doesn't prematurely end the scan, and `${...}` interpolations
 * inside template literals are tracked as their own bracket depth so
 * they don't confuse the outer paren count either. */
function extractCallArguments(source: string, openParenIndex: number): string {
  let depth = 0;
  let i = openParenIndex;
  let quote: '"' | "'" | '`' | null = null;
  let templateExprDepth = 0; // nested {} depth *inside* a `${ ... }`

  for (; i < source.length; i += 1) {
    const ch = source[i];
    const prev = source[i - 1];

    if (quote) {
      if (ch === '\\' && prev !== '\\') {
        // escape sequence — skip the next char's special meaning
        i += 1;
        continue;
      }
      if (quote === '`' && ch === '$' && source[i + 1] === '{') {
        templateExprDepth += 1;
        i += 1; // consume the '{' too
        continue;
      }
      if (quote === '`' && templateExprDepth > 0) {
        if (ch === '{') templateExprDepth += 1;
        if (ch === '}') templateExprDepth -= 1;
        continue;
      }
      if (ch === quote) {
        quote = null;
      }
      continue;
    }

    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
      continue;
    }
    if (ch === '(') {
      depth += 1;
      continue;
    }
    if (ch === ')') {
      depth -= 1;
      if (depth === 0) {
        return source.slice(openParenIndex + 1, i);
      }
    }
  }
  // Unbalanced (shouldn't happen in valid TS) — return the rest as a
  // conservative fallback so a real violation still gets caught.
  return source.slice(openParenIndex + 1);
}

interface Violation {
  file: string;
  line: number;
  token: string;
}

function findSecretLoggingViolations(): Violation[] {
  const violations: Violation[] = [];
  for (const file of listTsFiles(SRC_ROOT)) {
    const source = fs.readFileSync(file, 'utf-8');
    for (const match of source.matchAll(CONSOLE_CALL_RE)) {
      const openParenIndex = (match.index ?? 0) + match[0].length - 1;
      const args = extractCallArguments(source, openParenIndex);
      for (const token of SECRET_TOKENS) {
        if (new RegExp(`\\b${token}\\b`).test(args)) {
          const line = source.slice(0, openParenIndex).split('\n').length;
          violations.push({ file: path.relative(SRC_ROOT, file), line, token });
        }
      }
    }
  }
  return violations;
}

describe('secrets are never logged (Phase 13 Track A)', () => {
  it('finds at least one real console call site (scanner sanity check)', () => {
    let total = 0;
    for (const file of listTsFiles(SRC_ROOT)) {
      const source = fs.readFileSync(file, 'utf-8');
      total += [...source.matchAll(CONSOLE_CALL_RE)].length;
    }
    expect(total).toBeGreaterThan(0);
  });

  it('never interpolates a secret-bearing config field into a console.* call', () => {
    const violations = findSecretLoggingViolations();
    expect(violations, JSON.stringify(violations)).toEqual([]);
  });
});
