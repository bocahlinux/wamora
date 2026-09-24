# WAMORA Frontend Design Assets

This folder is the visual handoff package for the future frontend implementation.

## Important

These assets are **design references**, not yet production frontend assets.

When Phase 7/frontend implementation starts, Claude should read:

- `docs/WAMORA-FRONTEND-DESIGN-SPEC.md`
- all relevant images under `assets/reference/`

The generated PNGs are visual references. The logo crops under `assets/brand/` are also reference images; production branding should eventually be converted/approved as SVG masters.

## Recommended project placement

Copy this package into the repository root as:

```text
frontend-design-assets/
├── README.md
├── docs/
│   └── WAMORA-FRONTEND-DESIGN-SPEC.md
├── assets/
│   ├── brand/
│   ├── icons/
│   ├── screens/
│   └── reference/
└── ...
```

Do not copy the reference images into `frontend/src/assets/` until actual frontend implementation begins.

## Prompt for Claude

Use this at the beginning of the frontend phase:

> Before modifying frontend code, read `frontend-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` and inspect the relevant images in `frontend-design-assets/assets/reference/`. Treat the design specification as the visual source of truth. Reuse its color tokens, typography, Lucide icon mapping, component hierarchy, spacing, light/dark behavior, and responsive rules. Do not invent a different visual style. Implement only the scope assigned to the current coding phase.

## Asset status

- `brand/`: reference logo/icon crops
- `reference/`: complete visual design boards
- `icons/`: reserved for the production icon mapping
- `screens/`: reserved for page-specific approved references

Before production, create approved SVG logo masters and export platform-specific icons/favicon from those masters.
