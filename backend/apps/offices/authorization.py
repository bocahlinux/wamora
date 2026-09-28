"""Office/role authorization foundation — Step 3 of the multi-office
roadmap. Plain functions operating on `request.user` (matches this
project's existing style, e.g. `apps.blast.limits.remaining_daily_budget`
— no class-based service layer exists anywhere in this codebase, so none
is introduced here).

Deliberately the ONE place this logic lives — Blast/Inbox integration
(later steps) must call these functions, never re-derive
office/role/access logic themselves, so the rule is defined once.

Out of scope here, by design (later, per-feature steps): "can create a
campaign", "can approve", "can view an inbox conversation" — this module
only answers office/role/access questions, never business permissions.

Does not touch `apps.authn.jwt_utils.compute_scopes()`, JWT issuance/
verification, or `django.contrib.auth.models.Group` — scope (a
technical permission claim) and office/organizational-standing (both now
read from the same `OfficeMembership.role` -> `Role` row, per that
model's own docstring) remain two independent axes read independently:
this module never looks at `Role.scopes`, only at
`.grants_global_access`/`.is_office_admin`/`.is_operator`.
"""


def _authenticated(user) -> bool:
    return bool(user) and bool(getattr(user, 'is_authenticated', False))


def _membership(user):
    """The user's `OfficeMembership`, or `None` if they have none.
    `getattr(..., default)` is safe here: Django's reverse-OneToOne
    "does not exist" exception is itself a subclass of `AttributeError`
    (confirmed against this project's own model), which is exactly what
    `getattr`'s default argument catches."""
    if not _authenticated(user):
        return None
    return getattr(user, 'office_membership', None)


def is_superadmin(user) -> bool:
    return _authenticated(user) and bool(user.is_superuser)


def is_global_admin(user) -> bool:
    membership = _membership(user)
    return membership is not None and membership.role.grants_global_access


def is_office_admin_role(user) -> bool:
    """TRUE for a real `OfficeMembership` whose `Role` carries
    `is_office_admin` — administrative authority WITHIN that user's own
    Office (Blast approve/reject, chat assignment). Named with the
    `_role` suffix to avoid colliding with `Role.is_office_admin`, the
    field itself. Deliberately does NOT also return True for
    `has_global_access(user)` — every existing caller
    (`HasOfficeAdminAccess`, `_admin_scope()`) already ORs this together
    with a separate `has_global_access` check itself, same as before this
    merge."""
    membership = _membership(user)
    return membership is not None and membership.role.is_office_admin


def is_operator_role(user) -> bool:
    """TRUE for a real `OfficeMembership` whose `Role` carries
    `is_operator` — eligible as a chat-assignment target and may toggle
    their own availability (`apps.chats.assignment`,
    `OperatorAvailabilityView`)."""
    membership = _membership(user)
    return membership is not None and membership.role.is_operator


def get_user_office(user):
    """The `Office` this user belongs to, or `None` — for a Global Admin
    (office is NULL by Step 2's own constraint), a user with no
    membership, or a Superadmin (who needs none)."""
    membership = _membership(user)
    if membership is None:
        return None
    return membership.office


def has_global_access(user) -> bool:
    """True for Superadmin OR Global Admin — both see/act across every
    Office. False for Office Admin, Operator, and anyone with no
    membership at all."""
    return is_superadmin(user) or is_global_admin(user)


def can_access_office(user, office) -> bool:
    """Whether `user` may access a resource belonging to `office`.
    `office=None` is always False here — an ambiguous target is never
    silently treated as accessible, even for a globally-accessing user;
    callers with a real Office to check should pass it explicitly."""
    if office is None:
        return False
    if has_global_access(user):
        return True
    user_office = get_user_office(user)
    return user_office is not None and user_office.pk == office.pk
