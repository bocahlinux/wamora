# Claude Coding Guide

Before coding read:
1. CLAUDE.md
2. 00-MASTER-SPEC.md
3. phase-specific documents
4. relevant API/data/deployment documents.

For every task:
- state scope;
- inspect existing code;
- implement smallest coherent change;
- run tests/lint/type-check;
- report files changed, tests, limitations.

Do not generate the entire system in one pass. Current phase status and
what to work on next is tracked in `16-MASTER-ROADMAP.md` (canonical,
22-phase) — `15-CODING-PHASES.md` is the original engineering sequence,
kept for history but no longer the current authority.

Do not create PostgreSQL container, expose secrets, or make frontend call WAHA directly.

If ambiguity affects architecture/security/data integrity, ask before guessing.
