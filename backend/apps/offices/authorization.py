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
technical permission claim) and office/role (an organizational fact)
remain two independent axes, exactly as Step 2 established.
"""

from apps.offices.models import ROLE_GLOBAL_ADMIN


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
    return membership is not None and membership.role == ROLE_GLOBAL_ADMIN


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
