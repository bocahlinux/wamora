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

import logging

from django.contrib.auth.models import User
from django.db.models import F
from django.utils import timezone

from apps.blast.bff_client import BffDispatchError, send_blast_message
from apps.chats.models import Chat, ConversationSession
from apps.offices.authorization import has_global_access
from apps.offices.models import OfficeInboxConfig

logger = logging.getLogger(__name__)

USER_NOT_FOUND = 'user_not_found'
USER_INACTIVE = 'user_inactive'
NOT_OFFICE_MEMBER = 'not_office_member'
NOT_OPERATOR_ROLE = 'not_operator_role'
NOT_AVAILABLE = 'not_available'
NOT_ELIGIBLE = 'not_eligible'
ALREADY_CLAIMED = 'already_claimed'


def valid_assignment_candidates(office):
    """Users who may currently be assigned a Chat belonging to `office`:
    a real (current) `OfficeMembership` in exactly this Office, whose
    `Role` carries `is_operator` (Step 14's own deliberate minimal scope
    — an Office Admin/Global Admin is never itself an assignment TARGET,
    only an actor who may perform the assignment), `is_available=True`,
    and the Django account itself `is_active`. All axes checked
    independently, on purpose — see `apps.offices.models.OfficeMembership
    .is_available`'s own docstring for why they are never conflated."""
    if office is None:
        return User.objects.none()
    return User.objects.filter(
        is_active=True,
        office_membership__office=office,
        office_membership__role__is_operator=True,
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
        target = User.objects.select_related('office_membership', 'office_membership__role').get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return None, USER_NOT_FOUND

    if not target.is_active:
        return None, USER_INACTIVE

    membership = getattr(target, 'office_membership', None)
    if membership is None or membership.office_id != chat.office_id:
        return None, NOT_OFFICE_MEMBER
    if not membership.role.is_operator:
        return None, NOT_OPERATOR_ROLE
    if not membership.is_available:
        return None, NOT_AVAILABLE

    Chat.objects.filter(pk=chat.pk).update(assigned_to=target, updated_at=timezone.now())
    chat.refresh_from_db()
    return chat, None


def claim_chat(chat, user):
    """Self-assign — the "ambil" action a user performs on THEMSELVES
    (contrast `assign_chat_to_operator`, an admin assigning a third
    party). Discussed requirement: whoever sees a pending handoff on the
    dashboard (`apps.dashboard.views.PendingChatsView`) may claim it.

    Returns `(chat, None)` on success, or `(None, error_code)`:
      - `ALREADY_CLAIMED` — someone else already has it; never silently
        steals an in-progress conversation.
      - `NOT_ELIGIBLE` — the caller is none of: (a) a valid assignment
        candidate for `chat.office` (`valid_assignment_candidates` — real
        Operator membership, available, active), (b) an Office Admin of
        exactly that Office (active) — revised per discussion: unlike
        `assign_chat_to_operator` (an admin assigning a THIRD party,
        still Operator-only, Step 14's original convention unchanged
        there), an Office Admin MAY now claim/handle a chat themselves,
        not only delegate it to an Operator — or (c) a globally-accessing
        actor (Superadmin/Global Admin), who may ALWAYS claim any chat
        regardless of `chat.office` — found live: a Superadmin claiming a
        chat that already had a real Office (not just the `office=None`
        case) was wrongly rejected, since that bypass previously only
        applied when there was no Office at all. Global access must mean
        global access, same as everywhere else this project checks it
        (`chats_visible_to`/`can_manage_chat`)."""
    if chat.assigned_to_id == user.pk:
        return chat, None  # already claimed BY THIS SAME USER — a no-op, never re-notifies.
    if chat.assigned_to_id is not None:
        return None, ALREADY_CLAIMED

    if not has_global_access(user):
        if chat.office_id is None:
            return None, NOT_ELIGIBLE
        is_valid_operator = valid_assignment_candidates(chat.office).filter(pk=user.pk).exists()
        membership = getattr(user, 'office_membership', None)
        is_office_admin_here = (
            user.is_active and membership is not None
            and membership.office_id == chat.office_id and membership.role.is_office_admin
        )
        if not (is_valid_operator or is_office_admin_here):
            return None, NOT_ELIGIBLE

    Chat.objects.filter(pk=chat.pk).update(assigned_to=user, updated_at=timezone.now())
    chat.refresh_from_db()
    _send_claim_notification(chat, user)
    return chat, None


def _send_claim_notification(chat, user) -> None:
    """Discussed requirement — a citizen is told, in-chat, once a real
    person has picked up their conversation: the destination Office's
    own `OfficeInboxConfig.welcome_message` (Step 10 — previously never
    sent by any live flow, per that model's own docstring; this is its
    first consumer), followed by the claiming user's `initial`
    (`apps.offices.models.UserProfile` — set at account creation,
    self-editable via `apps.offices.views.MyProfileView`). Best-effort,
    same "never raises, a send failure is logged only" discipline as
    `apps.chats.conversation_engine._send` — claiming a chat must never
    fail or roll back just because the notification couldn't be sent.
    No-op for a `chat.office=None` chat (every accepting Office disabled,
    or a Superadmin/Global Admin claim with no Office to draw a welcome
    message from) — nothing configured to draw a message from."""
    if chat.office_id is None:
        return

    inbox_config = OfficeInboxConfig.objects.filter(office_id=chat.office_id).first()
    welcome = inbox_config.welcome_message.strip() if inbox_config else ''
    profile = getattr(user, 'profile', None)
    initial = profile.initial.strip() if profile and profile.initial else user.username
    signature = f'_~ {initial}_'  # WhatsApp italics (_..._) — '~' is a plain visual marker, not markup
    text = f'{welcome}\n\n{signature}' if welcome else signature

    try:
        send_blast_message(chat.session.name, chat.provider_chat_id, text, f'claim-{chat.pk}-{user.pk}')
    except BffDispatchError as exc:
        logger.warning('claim notification send failed for chat %s: %s', chat.pk, exc)


def transfer_chat(chat, target_office, user_id):
    """Superadmin/Global Admin ONLY (enforced by the view's permission
    check — `apps.chats.views.ChatTransferView`, this function's only
    caller) — discussed requirement: a globally-accessing actor may move
    an in-progress handoff to a DIFFERENT Office and a specific member
    of it, in one step. Unlike `assign_chat_to_operator`/`claim_chat`
    (same-Office only, and hard-blocked by
    `apps.chats.views._has_open_waiting_operator_session` while a
    handoff is open), this is the one action deliberately exempt from
    that block — its entire purpose IS redirecting an open handoff
    across Offices; the view never applies that check here.

    Target eligibility (in `target_office`, active): a valid Operator
    (`role.is_operator`, `is_available`) — same rule
    `assign_chat_to_operator` already enforces — OR an Office Admin of
    `target_office` (no availability concept for an Admin, same
    carve-out `claim_chat` already established).

    On success: `Chat.office`/`assigned_to` are updated together, and
    the Chat's own currently-open WAITING_OPERATOR session (if any) has
    its `office` updated to match — `ConversationSession.office`'s own
    field comment already defines it as "the Office THIS session routed
    its citizen to"; a transfer is a re-routing of that same session,
    not a new one. Returns `(chat, None)` on success, or
    `(None, error_code)` — `USER_NOT_FOUND`/`USER_INACTIVE`/
    `NOT_OFFICE_MEMBER`/`NOT_OPERATOR_ROLE`/`NOT_AVAILABLE`, the same
    vocabulary `assign_chat_to_operator` already uses."""
    try:
        target = User.objects.select_related('office_membership', 'office_membership__role').get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return None, USER_NOT_FOUND

    if not target.is_active:
        return None, USER_INACTIVE

    membership = getattr(target, 'office_membership', None)
    if membership is None or membership.office_id != target_office.pk:
        return None, NOT_OFFICE_MEMBER
    if membership.role.is_operator:
        if not membership.is_available:
            return None, NOT_AVAILABLE
    elif not membership.role.is_office_admin:
        return None, NOT_OPERATOR_ROLE

    Chat.objects.filter(pk=chat.pk).update(office=target_office, assigned_to=target, updated_at=timezone.now())
    ConversationSession.objects.filter(
        chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR,
    ).update(office=target_office, updated_at=timezone.now())
    chat.refresh_from_db()
    return chat, None


def unassign_chat(chat):
    """Clears `chat.assigned_to` — the Chat itself is never removed from
    the Inbox or hidden by this (Office visibility is entirely
    `apps.chats.authorization.chats_visible_to`'s job, unchanged)."""
    Chat.objects.filter(pk=chat.pk).update(assigned_to=None, updated_at=timezone.now())
    chat.refresh_from_db()
    return chat
