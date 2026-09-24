# WAMORA Asset Integration Guide

## 1. Where to put this package

Place the whole directory at repository root:

`frontend-design-assets/`

Do not scatter the reference files through `frontend/src/`.

## 2. What should be committed

The design specification and reference images can be committed to GitHub if they contain no production credentials or private operational data.

Do not put `.env`, API keys, database passwords, real WhatsApp identifiers, or production screenshots into this directory.

## 3. What happens later in Phase 7

Claude should first inspect this package, then implement production assets inside the frontend according to the project's existing build conventions.

Suggested production structure:

```text
frontend/src/
├── assets/
│   ├── brand/
│   └── ...
├── components/
├── layouts/
├── pages/
└── ...
```

Only approved production assets should be copied there.

## 4. Logo

The current PNG logo crops are visual references. They should not be treated as canonical vector masters.

Before production release:

- approve the final WAMORA mark;
- create SVG horizontal logo;
- create SVG compact mark;
- create light/dark variants;
- export favicon/app icons;
- verify clear-space and minimum-size rules.

## 5. Icons

Use Lucide consistently. Do not create dozens of custom SVG icons just to match the reference board.

## 6. Screenshots/reference boards

Use them to understand visual hierarchy, not as a source of hardcoded dimensions.

## 7. Keeping Claude aligned

Every frontend prompt should include:

- read `frontend-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md`;
- inspect the relevant reference images;
- do not invent a new visual language;
- preserve light/dark parity;
- use Lucide;
- use the defined semantic color system;
- reuse components.

