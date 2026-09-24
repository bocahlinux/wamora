# Repository Structure

```text
waha-dashboard/
├── CLAUDE.md
├── README.md
├── docs/
├── frontend/
├── bff/
├── backend/
├── infrastructure/
│   ├── tencent/
│   └── office/
└── scripts/
```

## Ownership
frontend = UI
bff = Tencent WAHA boundary
backend = Django data/business layer
infrastructure = deployment
docs = specification
PostgreSQL = external existing infrastructure

A task scoped to one component should not modify another unless integration/API contract requires it.
