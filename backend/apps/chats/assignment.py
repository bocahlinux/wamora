"""Step 14 — Chat -> Operator assignment foundation.

Deliberately manual-only: no round-robin/least-loaded/priority-queue/
auto-assignment-on-arrival logic exists here (none was found anywhere in
this codebase during the Step 14 audit, and building one is explicitly
out of this step's scope). This module only answers two questions:

  1. Which Users may currently be assigned a Chat belonging to a given
     Office? (`valid_assignment_candidates`)
  2. Given a chosen User ID, is it still a valid assignment target, and
     if so, assign it? (`assign_chat_to_operator`)

Both re-derive the answer from the database on every call — the exact
same "never trust a previously-shown list, always re-check live" pattern
`apps.chats.operator_chat.select_office_for_chat` (Step 11) already
established for Office selection.

Deliberately does NOT re-derive Office/role authorization itself —
`apps.offices.authorization`/`apps.chats.authorization` remain the only
place that logic lives. This module only adds the ONE additional rule
those don't already answer: "is this specific User a valid Operator for
this specific Chat's Office, right now" (membership office match + role +
active + available) — a target-validity question, not a viewer-
authorization question (that stays `can_view_chat`, enforced in the view,
unchanged).
"""

from django.contrib.auth.models import User
from django.db.models import F
from django.utils import timezone

from apps.chats.models import Chat
from apps.offices.models import ROLE_OPERATOR

USER_NOT_FOUND = 'user_not_found'
USER_INACTIVE = 'user_inactive'
NOT_OFFICE_MEMBER = 'not_office_member'
NOT_OPERATOR_ROLE = 'not_operator_role'
NOT_AVAILABLE = 'not_available'


def valid_assignment_candidates(office):
    """Users who may currently be assigned a Chat belonging to `office`:
    a real (current) `OfficeMembership` in exactly this Office, role
    `operator` (Step 14's own deliberate minimal scope — an Office
    Admin/Global Admin is never itself an assignment TARGET, only an
    actor who may perform the assignment), `is_available=True`, and the
    Django account itself `is_active`. All three axes checked
    independently, on purpose — see `apps.offices.models.OfficeMembership
    .is_available`'s own docstring for why they are never conflated."""
    if office is None:
        return User.objects.none()
    return User.objects.filter(
        is_active=True,
        office_membership__office=office,
        office_membership__role=ROLE_OPERATOR,
        office_membership__is_available=True,
    ).annotate(is_available=F('office_membership__is_available')).order_by('username')


def assign_chat_to_operator(chat, user_id):
    """Validates `user_id` against the database (never trusting a
    previously-fetched candidate list) and, if still valid, sets
    `chat.assigned_to`. Returns `(chat, None)` on success, or
    `(None, error_code)` on failure — one of `USER_NOT_FOUND`,
    `USER_INACTIVE`, `NOT_OFFICE_MEMBER` (not a member of THIS chat's
    Office — covers both "different Office" and "no Office/Global Admin
    with no Office at all"), `NOT_OPERATOR_ROLE`, or `NOT_AVAILABLE`.

    Concurrency: a plain single-row `UPDATE` is atomic at the database
    level and reassignment is a normal, expected operation (unlike a
    state-machine transition, there is no "invalid prior state" for
    `assigned_to` to protect against) — two near-simultaneous assign
    calls simply resolve to whichever commits last, a fully consistent
    final state either way; no compare-and-set is needed here (contrast
    with `apps.blast.views`' approve/reject, which DOES compare-and-set
    because an invalid status transition is a real error there)."""
    try:
        target = User.objects.select_related('office_membership').get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return None, USER_NOT_FOUND

    if not target.is_active:
        return None, USER_INACTIVE

    membership = getattr(target, 'office_membership', None)
    if membership is None or membership.office_id != chat.office_id:
        return None, NOT_OFFICE_MEMBER
    if membership.role != ROLE_OPERATOR:
        return None, NOT_OPERATOR_ROLE
    if not membership.is_available:
        return None, NOT_AVAILABLE

    Chat.objects.filter(pk=chat.pk).update(assigned_to=target, updated_at=timezone.now())
    chat.refresh_from_db()
    return chat, None


def unassign_chat(chat):
    """Clears `chat.assigned_to` — the Chat itself is never removed from
    the Inbox or hidden by this (Office visibility is entirely
    `apps.chats.authorization.chats_visible_to`'s job, unchanged)."""
    Chat.objects.filter(pk=chat.pk).update(assigned_to=None, updated_at=timezone.now())
    chat.refresh_from_db()
    return chat
