# Group/User Architecture — Audit + Technical Design (read-only)

**Scope of this task.** Audit-only, technical design only. No model, no
migration, no code, no test, and no database change was made. Blast and
Inbox were read, not modified — the Blast self-approval fix from the
prior task (Django superuser exception) was independently re-verified
present and is treated as already-closed, not redone. Nothing committed
or pushed.

---

## 1. Current User/Auth Architecture

- **No custom user model.** `AUTH_USER_MODEL` is not set anywhere in
  `backend/config/settings.py` — the project uses Django's stock
  `django.contrib.auth.models.User` unchanged.
- **JWT is the only session mechanism.** `apps/authn/jwt_utils.py`
  issues tokens (`issue_access_token`); `apps/authn/authentication.py`'s
  `JWTAuthentication` verifies them for Django's own directly-called
  endpoints (`/api/auth/me/`, `/api/dashboard/*`, and by extension every
  other frontend-facing Django view, including Blast's). The BFF
  verifies independently with only the public key
  (`bff/src/jwt.ts`, not re-audited here).
- **`request.user` is always live**, re-fetched from the database on
  every request (`JWTAuthentication.authenticate()`:
  `User.objects.get(pk=payload['sub'], is_active=True)`) — it is *not*
  reconstructed from token claims. Any permission check that reads
  `request.user.groups`/`request.user.is_superuser`/a future
  `request.user`-related membership will always see the current
  database state, even though the token itself is only 8 hours long
  with no refresh.
- **`request.auth` is the raw decoded JWT payload** (a dict with `sub`,
  `iss`, `aud`, `iat`, `exp`, `scopes`) — this is what
  `HasReadingScope`/`HasBlastScope`/etc. read (`claims.get('scopes',
  [])`), not `request.user`.
- **No Role/Permission model.** `compute_scopes()`'s own docstring
  states this is deliberate: "Deliberately does not touch
  `django.contrib.auth.Permission` — Group membership is the simplest
  mechanism..." No custom Role table exists anywhere in `apps/*/models.py`
  (confirmed by grep).
- **How users are created**: `apps/authn/urls.py` exposes exactly two
  routes, `login/` and `me/` — **no registration/create-user endpoint
  exists anywhere in the application.** Users are created only via
  Django admin (`/admin/`, itself gated by `is_staff`/`is_superuser`,
  separately audited elsewhere) or `manage.py createsuperuser`/shell —
  an infrastructure/ops action, not an application feature.
- **How the frontend knows the current user**: `GET /api/auth/me/`
  (`MeView`) returns `{id, username, display_name, is_superuser}` —
  deliberately minimal, **no scopes, no groups**. Scopes come
  separately, baked into the JWT itself and decoded client-side
  (`frontend/src/lib/AuthContext.tsx`'s `claims`, read via
  `decodeToken()`), never fetched live from `/me/`.
- **Frontend authorization mechanism**: every gated page/action reads
  `claims?.scopes.includes(SOME_SCOPE_CONSTANT)` directly (e.g.
  `BlastDetailPage.tsx`'s `BLAST_SCOPE`/`SYSTEM_ADMINISTRATION_SCOPE`
  constants) — a client-side convenience only; every one of these
  scopes is independently re-checked server-side by a matching DRF
  permission class. `is_superuser` is the one exception fetched live
  (via `/me/`, not the JWT) specifically for the Blast self-approval UX,
  per that view's own comment.

## 2. Current Role/Scope Architecture

- **Six fixed scope strings**, `settings.JWT_SCOPES`: `reading`,
  `sending`, `session control`, `blast`, `user administration`,
  `system administration`. No "office"/"group"/"tenant" scope exists.
- **`apps/authn/jwt_utils.py:compute_scopes(user)`** — the entire scope
  mechanism:
  ```python
  if user.is_superuser:
      return list(settings.JWT_SCOPES)          # every scope, unconditionally
  group_names = set(user.groups.values_list('name', flat=True))
  return [scope for scope in settings.JWT_SCOPES if scope in group_names]
  ```
  A non-superuser gets scope `"blast"` **only if** they belong to a
  `django.contrib.auth.models.Group` literally named `"blast"`. This is
  the **only** place Django's built-in `Group` model is used anywhere
  in this codebase (confirmed by grep across `apps/*/models.py` and
  `apps/*/views.py` — no other reference to `.groups` found outside
  `jwt_utils.py`/tests).
- **Enforcement**: `apps/authn/permissions.py` — `HasReadingScope`,
  `HasSystemAdministrationScope`, `HasBlastScope`, each a ~5-line class
  checking `'<scope>' in claims.get('scopes', [])`. No queryset-level
  filtering exists in *any* of these — they are all-or-nothing gates on
  a *view*, never on *which rows* of data a granted caller can see.
- **Scope changes require re-login** — the JWT is decoded client-side
  and used as-is for its full 8-hour life; there is no refresh
  endpoint. Changing a user's Group membership does not take effect
  until their next login. This already applies to every existing scope
  today — not a new limitation introduced by this design.

## 3. Current Blast Architecture

- **`BlastCampaign`** (`apps/blast/models.py`): `session` (FK to
  `WahaSession`), `name`, `message_template`, `status`, `created_by`
  (FK to `AUTH_USER_MODEL`), `approved_by`, `approved_at`,
  `rejected_reason`. **No group/tenant/office field of any kind.**
- **List/create** (`BlastCampaignListCreateView`,
  `apps/blast/views.py:47`): `GET` returns
  `BlastCampaign.objects.select_related(...).order_by('-created_at')`
  — **completely unfiltered**. Any authenticated caller holding
  `blast` OR `system administration` sees **every campaign from every
  creator**, today, with no ownership restriction whatsoever. `POST`
  requires `blast` scope only; `created_by` is set from
  `request.user` in the serializer (not independently audited line-by-
  line here, but confirmed to be the creator, per the view's own
  docstring and the reproduction from the prior task).
- **Detail** (`BlastCampaignDetailView`): same non-filtered pattern —
  any ID, any caller with the read scope, no ownership check.
- **Submit** (`BlastCampaignSubmitView`): creator-only (`created_by_id
  != request.user.id` → 403).
- **Approve** (`BlastCampaignApproveView`) — re-verified this task,
  current, correct state: `system administration` scope required;
  `campaign.created_by_id == request.user.id and not
  request.user.is_superuser` → 403 (the fix from the prior task,
  confirmed present, not re-implemented here); budget check; audit log;
  schedules `schedule_blast_campaign_task`.
- **Reject** (`BlastCampaignRejectView`): `system administration` scope
  only — **no creator restriction at all**, by original design.
- **Dispatch**: `schedule_blast_campaign_task` (Celery) → per-recipient
  tasks → `apps/blast/bff_client.py` → BFF `/internal/blast/send` →
  WAHA. None of this reads or needs any group/office concept — it
  already operates on a single, already-resolved `campaign_id`.

**Bottom line**: today, "who created it" is the *only* ownership
concept anywhere in Blast, and it gates exactly two actions (submit,
and the reversed self-approval check) — it has never gated *visibility*
at all. Adding office-based visibility is net-new work, not a
modification of an existing filter.

## 4. Existing Group Mechanism — is it safe to reuse for "Samsat Group"?

**No — a separate model is the right call, and here is why, from source:**

1. **`django.contrib.auth.models.Group` is already a single-purpose
   mechanism today**: its `name` field is matched *by string equality*
   against `settings.JWT_SCOPES` to grant scopes. If "Samsat Palangka
   Raya" were created as a `Group` row, it would not accidentally grant
   a scope (its name doesn't match any of the 6 fixed scope strings) —
   so it would not be functionally *broken* — but it would sit in the
   exact same table and the exact same `user.groups` relation as
   scope-groups, with no way to distinguish "this Group represents a
   permission scope" from "this Group represents an office" other than
   by convention. Any future admin screen listing a user's Groups would
   show a jumbled mix of both. This is a real design smell, not a
   hypothetical one — the ambiguity `compute_scopes()` would face if an
   office's name ever *did* collide with a scope name (e.g., an office
   literally named "reading" or "sending") is a latent, if unlikely,
   bug waiting to happen.
2. **A second, unrelated naming collision already exists in this
   codebase**: `apps/chats/models.py`'s `Chat.is_group` means "this is a
   WhatsApp group chat" — a third, completely different sense of
   "group." Naming the new business concept literally `Group` would
   create a *three-way* collision across the codebase (Django auth
   Group, WhatsApp group chat, Samsat office group). **Recommendation:
   name the new model something else** (e.g. `Office`, used throughout
   the rest of this report) — purely a naming choice, flagged for your
   decision, not decided unilaterally.
3. **Membership semantics don't fit either.** Django's `Group` carries
   no per-membership metadata — a user is simply "in" or "not in" a
   Group, with no way to record *which role* they hold within it
   (Admin vs Operator). The business design explicitly needs
   per-office role, which `Group` cannot represent without a second,
   parallel structure anyway.

**Conclusion**: keep Django's `Group` exactly as-is for its current,
narrow scope-granting purpose (do not touch it). Build a **new, custom
model** for the Samsat/office concept, with its own membership table
that also carries a role. This is Section 7's `Office`/
`OfficeMembership` proposal.

---

## 5. Proposed User/Group Architecture

| Role | Representation |
|---|---|
| **SUPERADMIN** | Already exists — `User.is_superuser = True`. No change. Continues to get every JWT scope via `compute_scopes()`, unchanged. |
| **GLOBAL ADMIN / Admin Asisten** | **New** — a non-superuser with cross-office visibility. Recommended representation: a new JWT scope (e.g. `"global administration"`) added to `settings.JWT_SCOPES`, granted via a same-named `django.contrib.auth.Group` — this reuses the *existing, already-working* mechanism exactly as-is (no new plumbing needed for issuance/verification), and keeps the "which scopes exist" list in one place. The *effect* of this scope (cross-office visibility) is new application logic (Section 11), but *granting* it reuses what's already there. |
| **GROUP ADMIN (Office Admin)** | **New** — represented by `OfficeMembership.role = 'admin'` for a specific `Office` row (Section 7). Does *not* need a new JWT scope by itself if `blast`/`system administration` scopes are still what gate *actions* (create/approve) — office admin-ness only narrows *which office's* campaigns those actions apply to, checked against `OfficeMembership`, not the JWT. |
| **GROUP OPERATOR (Office Operator)** | **New** — `OfficeMembership.role = 'operator'`. Same mechanism as Office Admin, different role value. |

This keeps two independent axes cleanly separated, matching what
already exists structurally: **JWT scopes answer "can this user perform
this *kind* of action at all" (unchanged); `OfficeMembership` answers
"within which office(s)."** Neither axis needs to know about the other
— a view combines both (e.g. "has `blast` scope AND is a member of the
target office").

---

## 6. Proposed Authorization Matrix

Pure capability matrix, no subjective ranking:

| Capability | SUPERADMIN | GLOBAL ADMIN | GROUP ADMIN | GROUP OPERATOR |
|---|---|---|---|---|
| See list of Offices | All | All (if cross-office visibility is granted to this role — see open question below) | Own office(s) only | Own office(s) only |
| See Campaigns | All offices | All offices (same condition as above) | Own office(s) only | Own office(s) only |
| Create Campaign | Any office (must still pick one) | Any office they administer, or any (per the same condition) | Own office(s) only | Own office(s) only, if scope allows (unchanged: `blast` scope required) |
| Approve Campaign | Any office, including own (superuser exception, already implemented) | Campaigns in offices they administer | Campaigns in own office **not created by self**, unless also superadmin | Cannot approve (needs `system administration` scope, which Operators are not assumed to hold — configurable per real deployment, not assumed here) |
| Reject Campaign | Any office | Offices they administer | Own office(s) only | Same as Approve — gated by scope, not role name |
| See Inbox (future) | All offices | All offices (same condition) | Own office(s) only | Own office(s) only |
| Manage Office members | All offices | Offices they administer (if granted) | Own office(s) only | No |
| Manage Office config (future: welcome/waiting/offline messages) | All offices | Offices they administer (if granted) | Own office(s) only | No |

**Open question this report cannot answer unilaterally**: whether
GLOBAL ADMIN's cross-office visibility is *unconditional* (same as
Superadmin, just without the "can approve own campaign" exception) or
itself *permission-gated per office* (e.g. explicitly assigned to
specific offices, functionally identical to a multi-office Group
Admin). Your own notes flag this as undecided ("Kita perlu menentukan
apakah Global Admin juga bisa lintas Group berdasarkan permission") —
Section 15's Decisions Required lists this explicitly.

---

## 7. Proposed Data Model (conceptual — no migration)

```
Office
  id
  name                (unique)
  is_active
  created_at / updated_at
  # inbox_enabled / welcome_message / waiting_message / offline_message
  # — explicitly NOT added now (deferred, per your instruction)

OfficeMembership
  id
  user        -> FK auth.User
  office      -> FK Office
  role        (choices: 'admin', 'operator')
  created_at / updated_at
  unique_together: (user, office)   # one role per user per office

BlastCampaign  (existing model, ADDING one field)
  office      -> FK Office, null=True, blank=True   # nullable — see Section 10
  ... (every existing field unchanged)
```

**Relation questions, answered from what the business description
already implies, flagged where a real decision is still needed:**

- **User → Office**: many-to-many, via `OfficeMembership` (not a plain
  FK on `User`) — this is a genuine decision point, not assumed.
  Reasoning: your own notes say a user "idealnya" (ideally) has one
  office — that word choice itself implies the *common* case is single-
  membership, but not necessarily a hard rule (e.g. a roaming
  admin covering two Samsat offices is plausible). A through-table
  supports both: single-membership can be an *application-enforced*
  convention (e.g. the UI only lets you pick one at a time) without
  requiring a schema constraint that would need a migration to lift
  later if that assumption changes. **Decision needed**: is
  multi-office membership something the business genuinely wants
  supported later, or should it be a hard single-office FK now?
- **Campaign → Office**: one Campaign belongs to exactly one Office
  (a single FK, not M2M) — this matches the business example directly
  ("Campaign #101, group = Samsat Palangka Raya") and there is no
  stated need for a campaign to span multiple offices.
- **Is Office required on Campaign?** For non-superadmin creators: yes,
  effectively required (a non-superadmin only has an office through
  their own membership, so it's a natural default, not usually a free
  choice). For a Superadmin or Global-Admin-created campaign:
  **decision needed** — does the business want to allow a "no specific
  office" campaign (visible to everyone, belonging to no one), or
  should even a Superadmin be required to pick a real office for every
  campaign (simpler mental model, no separate "campaign with no
  office" visibility rule to design)? This report recommends requiring
  a real office even for Superadmin-created campaigns (simpler,
  consistent, no second visibility carve-out) but does not decide it.
- **Where is role stored**: on `OfficeMembership` itself (`role` field
  on the through-table), not as a separate Django `Group` — keeping
  the office/role concept entirely inside the new model, fully
  independent of the existing scope-`Group` mechanism (Section 4).
- **Ownership vs. visibility, kept separate**: `created_by` (already
  exists) stays exactly what it means today — *who made this row*.
  `office` is an orthogonal *visibility/boundary* field — *who is
  allowed to see/act on this row at all*. Keeping them separate (rather
  than, say, inferring visibility from `created_by`'s own office at
  query time) means an office's membership can change later without
  needing to backfill every campaign's visibility.

**Reusability for Inbox, confirmed by design**: `Office` and
`OfficeMembership` as specified above have no Blast-specific fields —
`Chat`/`Conversation` (future) would gain the exact same kind of
`office` FK, and the exact same `OfficeMembership.role` would gate
Inbox actions (reply, handoff) the same way it gates Blast actions.
Nothing here is Blast-specific except the one added field on
`BlastCampaign` itself.

---

## 8. Blast Integration Points

Exact files/methods that would need to change **when this is
implemented** (not now):

| File | Change needed |
|---|---|
| `backend/apps/blast/models.py` | Add `office` FK to `BlastCampaign` (nullable). |
| `backend/apps/blast/serializers.py` | `BlastCampaignCreateSerializer` must accept/validate `office` (or infer it from the creator's own `OfficeMembership` if they belong to exactly one). |
| `backend/apps/blast/views.py` — `BlastCampaignListCreateView.get()` | Add office-scoped queryset filtering — **today there is none at all** (Section 3); this is the single most important enforcement point. |
| ...`.post()` | Validate/assign `office` consistently with the creator's own membership. |
| ...`BlastCampaignDetailView.get()` | Add a per-object office check after `get_object_or_404` — today any ID is readable by any scoped caller. |
| ...`BlastCampaignApproveView.post()` / `RejectView.post()` | Add the same per-object office check, composed with the existing self-approval/scope checks — must not weaken or replace them. |
| ...`BlastRecipientResolveView` | Same per-object office check, for consistency. |
| `backend/apps/blast/admin.py` | Optional: show/filter by `office` in the Django admin read view (already read-only by design, low priority). |
| `backend/apps/blast/tasks.py` | **No change expected** — dispatch already operates on an already-resolved `campaign_id`; office boundary is enforced before dispatch is ever triggered, not during it. |

---

## 9. Future Inbox Integration Points (design-only, not built)

- `backend/apps/chats/models.py` — `Chat` would gain an `office` FK
  (nullable until the WhatsApp-side menu-selection flow — itself
  explicitly not-yet-phased per `docs/11`'s "auto-reply bot" candidate
  requirement — actually resolves it per conversation).
- `backend/apps/chats/views.py`/`api_urls.py` — the same office-scoped
  queryset pattern as Blast's list/detail views (Section 8) would need
  to be applied to chat/message list and detail endpoints.
- `OfficeMembership.role` gates Inbox actions the same way it would
  gate Blast actions (e.g. only Office Admin/Operator of a chat's own
  office can reply; Superadmin/Global-Admin per Section 6's matrix).
- The Group Inbox configuration fields you described (`inbox_enabled`,
  `welcome_message`, `waiting_message`, `offline_message`) map directly
  onto `Office` as additional fields — **not added now**, but the model
  shape already accommodates them without redesign.
- Session-1x24h conversation windowing is unrelated to the
  Office/authorization boundary and is correctly out of this task's
  scope entirely.

---

## 10. Legacy Campaign Migration Considerations

- **Current real state** (re-verified this task, read-only): all 5
  existing `BlastCampaign` rows (`id=1..5`) have `created_by=udin`, the
  only user in the database. None have any office concept today (the
  field doesn't exist yet).
- **`office` must be nullable**, at minimum transitionally — adding a
  `NOT NULL` FK to a table with existing rows would require a backfill
  decision *before* the migration could even run, and this report is
  explicitly not deciding that now.
- **Recommended default for existing rows**: leave `office = NULL`
  permanently unless/until someone deliberately reassigns them. Under
  the matrix in Section 6, a NULL-office campaign would be visible only
  to Superadmin (and Global Admin, if their cross-office visibility is
  unconditional) — never to any Office Admin/Operator. This is a safe,
  non-destructive default that requires no data assumption.
- **No risk to already-terminal campaigns**: the one `rejected`
  campaign and any future `completed`/`failed` ones are untouched by
  adding a visibility dimension — `office` is additive, never
  interacts with `status`/dispatch state.
- **This report does not run any migration** — Section 15 lists this as
  a later, separate, reviewed step.

---

## 11. Backend Enforcement Strategy

**Core principle** (directly answering Langkah 6): office boundaries
must be enforced in Django's queryset/permission layer, on every read
and write path, never left to frontend filtering. Concretely:

- **Centralize the check.** Add one small, shared helper (e.g. a new
  `backend/apps/offices/authorization.py` or similar — exact placement
  is an implementation decision for the later task, not this one) that
  answers two questions from `request.user`:
  1. Which office IDs may this user see/act within? (Superadmin/
     unconditional-Global-Admin → all; everyone else → their own
     `OfficeMembership` rows.)
  2. What role do they hold in a *specific* office? (for approve/reject
     gating within that office.)
- **Apply it at every layer that currently has none**:
  - List views: `.filter(office_id__in=<allowed ids>)` (or no filter at
    all for the "sees everything" roles).
  - Detail/approve/reject/resolve views: after `get_object_or_404`,
    check the object's `office_id` against the same helper; deny
    (following whatever the project's existing convention is — this
    codebase currently returns `403 forbidden` for scope/creator
    denials, e.g. the self-approval check, so an office-boundary denial
    should likely follow the same `403` pattern for consistency, not
    a `404` — a small consistency decision for the implementing task).
  - Any future Inbox chat/message view: the identical pattern, reusing
    the same helper — this is exactly why centralizing it now matters:
    a single place to get right, not one copy per app.
- **Compose with existing checks, never replace them.** E.g. Approve's
  final check becomes: has `system administration` scope AND (is
  superuser OR is not the creator) AND (is superadmin/unconditional-
  global-admin OR is an admin-role member of the campaign's own
  office). Every existing condition stays exactly as it is today.

---

## 12. Frontend Changes Needed Later (not now)

- `MeView`/`GET /api/auth/me/`: would need to additionally return the
  caller's office membership(s) + role (mirroring how `is_superuser`
  was added specifically for the approval UX) — the natural, minimal
  extension point, already proven as a pattern.
- `BlastListPage.tsx`: display the office per campaign; for Superadmin/
  Global-Admin, a filter/tab by office; for everyone else, no visible
  change needed since the backend already only returns their own
  office's campaigns.
- `BlastCreatePage.tsx`: an office-selection control if the creator
  belongs to more than one office (auto-filled if exactly one).
- `BlastDetailPage.tsx`: `canApprove`/`canReject` extended to also
  reflect "is this an admin of the campaign's office" — purely a UI
  convenience; the backend remains the authoritative check regardless
  of what the frontend computes.
- No change needed to route/menu-level scope gating (`blast`/`system
  administration` visibility) — office-awareness is a *within-page*
  concern, not a route-access concern.

---

## 13. Test Strategy (design only — none written)

Following this project's existing convention exactly (e.g.
`apps/blast/tests/test_views.py`'s `BlastCampaignApproveTests` class
shape — `self._user(username, scopes=[...])` helpers already exist and
would extend naturally to also attach an `OfficeMembership`):

- **A. Superadmin**: sees all offices; sees all campaigns regardless of
  office; can create a campaign for any office; can approve a campaign
  in any office, including their own (already covered by the existing
  self-approval-exception test — would gain an office dimension
  alongside it, not replace it).
- **B. Global Admin**: access strictly matches whatever permission
  they've been granted (Section 6's open question) — explicitly must
  **not** behave as a de facto superuser; a test should assert this
  distinction directly (e.g. cannot do something a real superuser-only
  action allows, if any such action exists).
- **C. Office Admin (e.g. Palangka Raya)**: sees/creates only Palangka
  Raya campaigns; a direct request for a Kasongan campaign's detail/
  approve/reject endpoint, by ID, must be denied — this is the
  cross-office boundary test and the single most important one to get
  right first.
- **D. Office Operator**: same visibility boundary as C, scoped by
  whatever action permissions Operators actually hold (create only, if
  `blast` scope is what they're granted; no approve without `system
  administration`).
- **E. Cross-office direct-ID access** — the concrete regression test:
  an authenticated user with valid scope, in Office A, requesting
  `GET/POST /api/blast/campaigns/<office-B-campaign-id>/...` for any of
  detail/approve/reject/resolve, must be denied by the backend, not
  merely hidden by the frontend.
- **F. Inbox (design-only, not implemented)**: the equivalent test
  shape to E — a chat/message belonging to Office A must never be
  retrievable by an Office B member via any endpoint, once Inbox
  gains office-awareness. Documented here as the shape a later task
  should follow; not written now.

**Existing coverage note**: `test_creator_holding_admin_scope_cannot_approve_own_campaign`
and the rest of `BlastCampaignApproveTests` (7/7 passing, re-run this
task) already correctly test the creator/superuser dimension — none of
them exercise an office dimension, since it doesn't exist yet. They
would need no changes, only additions alongside them.

---

## 14. Risks

- **Naming collision** if the new model is called `Group` — three
  unrelated meanings (`auth.Group`, `Chat.is_group`, business office)
  would coexist in one codebase. Mitigated by naming it something else
  (`Office` used throughout this report) — a decision for you, not
  assumed final.
- **Silent under-enforcement**: Blast's list/detail/approve/reject
  today have *zero* filtering to build on top of — a future
  implementer adding `office` to the model but filtering only the list
  view (forgetting detail/approve/reject) would leave a real,
  exploitable cross-office data leak. Mitigated by the centralized
  helper recommendation (Section 11) specifically to avoid four
  separate, easy-to-miss copies of the same check.
- **JWT staleness for Global Admin/role changes**: if Global-Admin
  cross-office visibility is represented as a JWT scope (Section 5),
  changing it takes effect only on next login — an existing limitation
  of the whole scope system today, not a new one, but worth remembering
  when designing the actual membership-change UX later.
- **Legacy campaigns becoming invisible** to Office Admins/Operators
  once office-filtering ships (Section 10) — acceptable and safe, but
  should be communicated, not silently discovered.
- **Scope creep into Blast** — every future step here must be strictly
  additive (new nullable field, new checks composed with existing
  ones) and must never touch the already-fixed self-approval policy or
  any dispatch logic, per your explicit instruction.
- **Migration sequencing risk** (not executed now): adding a nullable
  FK is low-risk by itself; a *future* decision to make it non-null
  would require a backfill plan first — flagged for whenever that
  decision is made, not a concern today.

---

## 15. Minimal Implementation Plan (staged, none executed)

1. **New model(s) only** — `Office`, `OfficeMembership` (with `role`).
   New app or placed in an existing one (exact location — a small
   decision for that task). Migration: new tables only, nothing on
   `BlastCampaign` yet.
2. **Add nullable `office` FK to `BlastCampaign`** + migration (no
   backfill, no default beyond NULL).
3. **Add the shared office-authorization helper** (Section 11) + the
   Global Admin scope/Group if that path is chosen (Section 5).
4. **Wire office filtering into Blast's four enforcement points**
   (list, detail, approve, reject/resolve) + serializer-level office
   assignment on create.
5. **Extend `MeView` + minimal frontend** (office info surfaced;
   list/detail/create pages updated) — Blast-only, still.
6. **Regression**: full existing Blast backend test suite must stay
   green throughout; add the new office-boundary tests (Section 13)
   alongside it, not replacing any existing test.
7. **Later, separate, not-yet-phased**: reuse `Office`/
   `OfficeMembership` for Inbox once that feature is formally scoped —
   explicitly out of this plan's own scope.

Each numbered step above is intended to be its own reviewed task, per
your "bertahap" instruction — this report does not recommend doing them
in one pass.

---

## Decisions Required From You (collected from Sections 5–7)

1. Is GLOBAL ADMIN's cross-office visibility unconditional (Superadmin-
   like, minus the self-approval exception) or itself permission-gated
   per office?
2. Can a user belong to more than one Office (many-to-many via
   `OfficeMembership`), or should this be a hard single-office rule
   (a plain FK) from the start?
3. Must every campaign have a real Office — including ones created by
   Superadmin/Global Admin — or should a "no office" campaign be a
   valid, intentionally-global state?
4. Naming: `Office` (this report's placeholder) vs. some other name —
   your call, given the collision risk explained in Section 4.
5. Denial status code for an office-boundary violation — `403` (matches
   existing self-approval-style denials) vs. `404` (hides existence) —
   a consistency choice for whoever implements Section 11.

---

## Explicit stop

This was an audit and technical design only. No model, migration, code,
test, or database row was created or changed. Blast's already-fixed
approval policy and dispatch flow were read, re-verified, and left
untouched. Nothing was committed or pushed. Awaiting your decisions
above before any implementation begins.
