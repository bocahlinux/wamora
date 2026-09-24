# WAMORA Frontend Visual Design System

**Project:** WAMORA — WhatsApp Operations & Monitoring  
**Document:** Frontend UI/UX Visual Design Specification  
**Purpose:** Authoritative visual handoff for the future frontend implementation  
**Status:** Design specification only — do not treat this document as implemented frontend code.

---

## 1. Purpose

This document defines the visual language that the WAMORA frontend should follow when frontend implementation begins.

The goal is **consistency**, not visual experimentation:

- Light and dark themes must use the same design language.
- Colors must come from the defined palette rather than ad-hoc values.
- Icons must come from one consistent icon family.
- Components should be reused instead of recreated page-by-page.
- Layout, spacing, typography, states, and interaction feedback should remain visually consistent.
- AI-generated visual assets are references; production UI should implement the rules below rather than copying screenshot pixels blindly.

### Source-of-truth order

When implementing the frontend:

1. Project functional specification in `docs/`
2. This visual design specification
3. Assets under `frontend-design-assets/`
4. Individual page mockups/reference images
5. Existing frontend code conventions

If a screenshot conflicts with this specification, the written specification wins.

---

## 2. Brand

### Product name

**WAMORA**

Recommended expansion:

**WhatsApp Operations & Monitoring**

The name is the application brand. Avoid reverting to the old generic product name "WAHA Monitoring Dashboard" in user-facing UI.

### Brand personality

WAMORA should visually communicate:

- operational
- reliable
- professional
- modern
- calm
- technical without looking like a developer tool
- suitable for institutional/internal operations

Avoid:

- excessive gradients
- neon cyberpunk styling
- glassmorphism everywhere
- excessive rounded "AI SaaS" cards
- random emoji as icons
- mixed icon families
- decorative effects that compete with operational information

---

## 3. Logo usage

### Required variants

The frontend should support these variants:

1. **Primary horizontal logo**
   - Logo mark + `WAMORA`
   - Used in desktop sidebar/header when enough horizontal space exists.

2. **Compact logo mark**
   - Icon only.
   - Used in collapsed sidebar, mobile header, favicon/app icon.

3. **Dark-background logo**
   - Full logo designed for dark surfaces.

4. **Monochrome light**
   - Dark/black logo for light surfaces where color is unnecessary.

5. **Monochrome dark**
   - White logo for dark surfaces.

### Rules

- Do not recolor the logo arbitrarily.
- Do not stretch or distort it.
- Do not add drop shadows to the logo unless the asset itself contains one.
- Preserve clear space around the mark.
- Prefer the compact mark at very small sizes rather than shrinking the complete wordmark until it becomes unreadable.

The current PNG files in `assets/brand/` are **visual references extracted from the generated design board**, not final vector masters. Before production branding, create/approve SVG masters.

---

## 4. Color system

The color system intentionally combines WAMORA green/teal with operational blue.

### Primary

| Token | Hex | Usage |
|---|---|---|
| `primary-500` | `#10B981` | Main WAMORA green, active/success-oriented UI |
| `primary-600` | `#059669` | Hover/strong green |
| `primary-400` | `#34D399` | Highlight/light green |
| `blue-600` | `#3B82F6` | Information, links, secondary emphasis |
| `blue-500` | `#2563EB` | Strong blue action/info |
| `blue-400` | `#60A5FA` | Light blue accents |

### Semantic colors

| Token | Hex | Meaning |
|---|---|---|
| `success` | `#22C55E` | Healthy, connected, successful |
| `warning` | `#F59E0B` | Warning, attention required |
| `error` | `#EF4444` | Error, failed, destructive |
| `info` | `#3B82F6` | Informational state |
| `offline` | `#94A3B8` | Offline/unavailable/neutral state |

### Light theme neutrals

| Token | Hex | Usage |
|---|---|---|
| `bg` | `#F8FAFC` | Application background |
| `surface` | `#FFFFFF` | Cards/panels |
| `surface-alt` | `#F1F5F9` | Secondary surface |
| `border` | `#E2E8F0` | Borders/dividers |
| `text-primary` | `#111827` | Main text |
| `text-secondary` | `#475569` | Secondary text |
| `text-muted` | `#64748B` | Muted/caption text |

### Dark theme neutrals

| Token | Hex | Usage |
|---|---|---|
| `bg-dark` | `#0F172A` | Main application background |
| `surface-dark` | `#1E293B` | Cards/panels |
| `surface-alt-dark` | `#334155` | Secondary surfaces |
| `border-dark` | `#475569` | Borders/dividers |
| `text-primary-dark` | `#F8FAFC` | Main text |
| `text-secondary-dark` | `#CBD5E1` | Secondary text |
| `text-muted-dark` | `#94A3B8` | Muted text |

### Important consistency rule

Do not use raw colors directly throughout React components.

Prefer semantic design tokens such as:

```text
color.primary
color.success
color.warning
color.error
surface.default
surface.raised
text.primary
text.secondary
border.default
```

The implementation technology may differ, but the semantic-token concept should remain.

---

## 5. Typography

### Font family

**Inter** is the preferred UI font.

Fallback:

```text
Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif
```

### Type scale

| Style | Size / line height | Weight | Usage |
|---|---:|---:|---|
| H1 | 32 / 40 | 700 | Page title |
| H2 | 24 / 32 | 600 | Section title |
| H3 | 20 / 28 | 600 | Card title |
| H4 | 16 / 24 | 500 | Subsection |
| Body | 14 / 20 | 400 | Main content |
| Body Small | 12 / 16 | 400 | Secondary content |
| Caption | 12 / 16 | 400 | Metadata |
| Button | 14 / 20 | 500 | Actions |

Avoid using many font sizes. Operational dashboards benefit from hierarchy and repetition.

---

## 6. Iconography

### Icon family

Use **Lucide Icons** consistently.

Do not mix:

- Font Awesome
- Material Icons
- random SVG icon packs
- emoji
- hand-drawn icons

unless a documented product requirement explicitly requires an exception.

### Style

- outline/stroke icons
- consistent stroke width
- simple geometry
- visually calm
- no decorative 3D icons

### Core icon mapping

| Concept | Preferred Lucide icon |
|---|---|
| Dashboard | `LayoutDashboard` |
| WhatsApp | `MessageCircle` |
| Inbox | `Inbox` |
| Sessions | `Smartphone` |
| Reports | `BarChart3` |
| Settings | `Settings` |
| Users | `Users` |
| Security | `ShieldCheck` |
| Search | `Search` |
| Notifications | `Bell` |
| Add | `Plus` |
| Edit | `Pencil` |
| Delete | `Trash2` |
| Start | `Play` |
| Stop | `Square` |
| Restart | `RefreshCw` |
| Logout | `LogOut` |
| QR | `QrCode` |
| Send | `Send` |
| Attachment | `Paperclip` |
| Image | `Image` |
| File | `File` |
| Success | `CircleCheck` |
| Warning | `TriangleAlert` |
| Error | `CircleX` |
| Info | `Info` |
| Filter | `ListFilter` |
| More | `MoreHorizontal` |

The exact icon component name may change with the installed Lucide version; the **visual family and semantic mapping** are the important part.

---

## 7. Layout

### Desktop

Target:

- sidebar: approximately 240–260px expanded
- content area: fluid
- max content width only where useful
- 16–24px page padding
- 16px card gap as default
- 24px section separation

### Sidebar

Navigation order:

1. Dashboard
2. WhatsApp
3. Inbox
4. Sessions
5. Reports
6. Settings

The exact final navigation should still follow the functional specification when implementation starts.

Sidebar behavior:

- expanded on desktop
- collapsible when appropriate
- compact icon-only mode must preserve tooltips
- active item uses WAMORA primary color treatment
- no excessive animation

### Header

Recommended:

- page/search context
- global search where applicable
- notifications
- theme toggle
- user/profile menu

The header should remain visually quiet so operational content dominates.

---

## 8. Core UI components

Build reusable components before building pages.

Required visual primitives:

- Button
- IconButton
- Input
- SearchInput
- Select
- Tabs
- Badge
- StatusBadge
- Card
- Modal/Dialog
- Drawer
- Dropdown
- Tooltip
- Toast/Notification
- DataTable
- EmptyState
- LoadingState/Skeleton
- ErrorState
- ConfirmDialog
- Pagination

### Button hierarchy

**Primary**
- important action
- WAMORA green/blue depending on semantic context

**Secondary**
- neutral supporting action

**Danger**
- destructive actions such as stop/delete/logout where applicable

Do not make every action a primary colored button.

---

## 9. Status visualization

Status must be understandable without relying only on color.

Example:

```text
● Healthy
● Warning
● Error
● Offline
```

Use:

- icon + text
- color
- optional tooltip/details

For WAHA sessions, visual states may include:

- WORKING
- SCAN_QR_CODE
- STOPPED
- FAILED
- STARTING
- UNKNOWN

The exact backend values must follow the actual API contract; the UI may map them into the visual system.

---

## 10. Dashboard visual structure

The dashboard should prioritize operational visibility.

Recommended structure:

### Row 1 — system health

Cards:

- WAHA
- Backend / Django
- PostgreSQL
- Redis

Each card:

- system icon
- status
- short operational detail
- optional latency/last-check

### Row 2 — sessions + activity

- WhatsApp sessions summary
- messages today / message volume
- system activity feed

### Row 3+

- trends
- reconciliation/sync indicators
- operational metrics
- future reports

Do not overfill the dashboard. The user should be able to understand the system state quickly.

---

## 11. Inbox / chat visual direction

The inbox is a high-density workflow and should not look like a marketing page.

Recommended desktop structure:

```text
┌──────────────┬─────────────────────────────┬──────────────┐
│ Chat list    │ Conversation               │ Contact info │
│              │                             │              │
│ Search       │ Header                      │ Contact      │
│ Filters      │ Messages                    │ Metadata     │
│ Conversations│ Composer                    │ Labels       │
└──────────────┴─────────────────────────────┴──────────────┘
```

Rules:

- received and sent messages must be visually distinct
- message timestamps should be subtle
- delivery/read indicators should be small
- attachments must use consistent icons
- conversation header should show session/contact context
- contact panel should never visually dominate the conversation

Dark mode must preserve the same hierarchy.

---

## 12. Session management visual direction

Session management is an operational control surface.

Each session card should expose:

- session name
- connection status
- phone/account identifier when allowed
- connected duration / last status
- message activity
- operational actions

Potential actions:

- Start
- Stop
- Restart
- Logout
- QR pairing

Destructive actions must require appropriate confirmation where specified by the security/functional contract.

QR pairing should be visually isolated in a modal/card rather than mixed into the main session card.

---

## 13. Dark mode

Dark mode is a first-class theme, not an afterthought.

### Rules

- Use the dark neutral palette.
- Preserve the same component geometry.
- Preserve semantic colors.
- Do not simply invert colors.
- Avoid pure black (`#000000`) as the main background.
- Use subtle surface separation.
- Keep borders visible but restrained.
- Reduce large shadows; use surface contrast instead.

### Theme consistency

A light-mode component and its dark-mode equivalent must represent the same semantic state.

For example:

```text
Healthy → green in both themes
Warning → amber in both themes
Error   → red in both themes
Info    → blue in both themes
```

Only luminance/contrast should change where required for accessibility.

---

## 14. Responsive design

### Breakpoints

Use the frontend framework's standard responsive breakpoints, but design around these conceptual ranges:

- Mobile: < 640px
- Tablet: 640–1023px
- Desktop: ≥ 1024px

### Mobile

- sidebar becomes navigation drawer/bottom navigation where appropriate
- three-column inbox collapses into a navigation flow
- tables become cards or horizontally scrollable where necessary
- primary actions remain accessible
- no tiny text to fit more information

### Tablet

- preserve dashboard cards but allow wrapping
- reduce sidebar width or collapse it
- inbox may become two-pane

### Desktop

- full navigation
- three-pane inbox
- multi-column dashboard

---

## 15. Interaction and motion

Motion should be subtle and operational.

Use:

- short hover/focus transitions
- drawer/modal transitions
- skeleton loading
- status transitions

Avoid:

- large entrance animations
- bouncing cards
- excessive parallax
- decorative animations

Recommended transition duration:

- 120–200ms for simple state changes
- 200–300ms for panels/dialogs

Respect `prefers-reduced-motion`.

---

## 16. Accessibility

Minimum expectations:

- keyboard navigable controls
- visible focus state
- sufficient text/background contrast
- semantic HTML
- aria labels for icon-only buttons
- status not conveyed by color alone
- dialogs must trap focus correctly
- tooltips must not be the only way to access essential information

---

## 17. Asset structure

Recommended repository location:

```text
frontend-design-assets/
├── README.md
├── WAMORA-FRONTEND-DESIGN-SPEC.md
├── brand/
│   ├── wamora-logo-horizontal.svg
│   ├── wamora-logo-horizontal-dark.svg
│   ├── wamora-logo-mark.svg
│   ├── wamora-logo-mark-dark.svg
│   ├── wamora-logo-monochrome.svg
│   ├── wamora-app-icon.png
│   └── wamora-favicon.png
├── icons/
│   ├── README.md
│   └── lucide-mapping.md
├── screens/
│   ├── dashboard-light.png
│   ├── dashboard-dark.png
│   ├── inbox-light.png
│   ├── inbox-dark.png
│   ├── sessions-light.png
│   ├── sessions-dark.png
│   └── mobile-reference.png
└── reference/
    ├── wamora-brand-guideline.png
    ├── wamora-ui-ux-specification.png
    ├── wamora-ui-design-system.png
    ├── wamora-visual-design-system.png
    └── wamora-frontend-reference.png
```

### Important

The assets should be copied into the project **as a design/reference package first**.

Do not place these files directly inside `frontend/src/assets/` until frontend implementation begins.

That keeps design references separate from production runtime assets.

---

## 18. What Claude should do when frontend implementation begins

Use this document as a mandatory visual reference.

A future implementation prompt should explicitly say:

> Read `frontend-design-assets/WAMORA-FRONTEND-DESIGN-SPEC.md` before changing frontend code. Treat it as the visual source of truth. Inspect all images under `frontend-design-assets/reference/` before implementing the relevant page. Reuse the defined color tokens, typography, Lucide icon mapping, spacing, component hierarchy, light/dark theme behavior, and responsive rules. Do not invent a new visual style.

Then constrain implementation to the phase requested by `docs/15-CODING-PHASES.md`.

Claude should:

1. inspect the current frontend code;
2. inspect the design specification;
3. inspect the relevant reference images;
4. identify reusable components;
5. implement the design system/components first when the phase calls for it;
6. implement pages using those components;
7. verify light mode;
8. verify dark mode;
9. verify responsive behavior;
10. run the relevant frontend tests/build.

---

## 19. Design acceptance checklist

Before accepting a frontend implementation:

### Brand
- [ ] WAMORA name is used consistently.
- [ ] Correct logo variant is used for the surface.
- [ ] No distorted logo.

### Color
- [ ] No random colors.
- [ ] Semantic colors are consistent.
- [ ] Light/dark palette is consistent.

### Typography
- [ ] Inter or the approved fallback is used.
- [ ] Heading hierarchy is consistent.
- [ ] No excessive font-size variations.

### Icons
- [ ] Lucide is used consistently.
- [ ] Same semantic action uses the same icon.
- [ ] No emoji replacing UI icons.
- [ ] No mixed icon families without explicit approval.

### Components
- [ ] Buttons follow hierarchy.
- [ ] Status badges are consistent.
- [ ] Inputs/cards/tables share the same visual language.
- [ ] Loading/error/empty states are consistent.

### Themes
- [ ] Light mode reviewed.
- [ ] Dark mode reviewed.
- [ ] Semantic colors remain recognizable.
- [ ] No unreadable dark-mode text.

### Responsive
- [ ] Mobile reviewed.
- [ ] Tablet behavior reviewed.
- [ ] Desktop reviewed.
- [ ] No critical control becomes inaccessible.

### Accessibility
- [ ] Keyboard navigation works.
- [ ] Focus state is visible.
- [ ] Icon-only controls have accessible labels.
- [ ] Status isn't communicated by color alone.

---

## 20. Design references included with this package

The `assets/reference/` directory contains generated visual reference boards showing:

- WAMORA logo/brand identity
- light and dark dashboard
- inbox/chat
- session management
- reports
- mobile layouts
- color system
- typography
- Lucide icon direction
- reusable UI components
- asset organization

These are **visual references**, not pixel-perfect implementation screenshots.

---

## 21. Final implementation principle

**Build WAMORA as one coherent product, not a collection of individually designed pages.**

The most important visual rule is consistency:

> Same color system + same typography + same icon family + same component geometry + same spacing + same light/dark semantics = WAMORA.

