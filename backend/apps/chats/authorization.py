"""Inbox/Chat <-> Office boundary — Step 5. The single place this rule
lives; every Chat view (list/messages/mark-read) filters or checks through
`chats_visible_to`/`can_view_chat`, never re-deriving role/office
comparison itself.

Built entirely from `apps.offices.authorization`'s existing primitives
(`has_global_access`, `get_user_office`) — no new office/role logic is
introduced here, only Chat-specific composition.

Deliberately DIFFERENT from `apps.blast.authorization`'s null-office
carve-out: Step 5's own spec is explicit that a user with no Office
membership gets NO Office Inbox access at all (not even a legacy
`office=None` chat) — unlike Blast, where that carve-out existed only to
preserve pre-Step-4 behavior for campaigns that already existed before
Office was introduced. Consequence: none of this project's existing Chat
rows (all `office=None`, no backfill was performed — see the model
field's own comment) are visible to an Office Admin/Operator/no-membership
user until a Chat is actually assigned a real Office (a later, WAHA/
session-to-office-mapping step, out of scope here) — only a
globally-accessing user (Superadmin/Global Admin) can see them meanwhile.
"""

from django.db.models import Q

from apps.offices.authorization import get_user_office, has_global_access


def chats_visible_to(user):
    """The `Chat` queryset `user` may see/act on.

    Matches EITHER `Chat.office` (the Chat's CURRENT Office — a single,
    mutable value that moves whenever a citizen picks a different Office
    in a later handoff round) OR any `Message.office` snapshot belonging
    to this user's Office (`Message.office`'s own field comment) — found
    live: a citizen who chatted with Palangka Raya, later re-selected
    Kasongan for a new round, made `Chat.office` move to Kasongan, which
    made Palangka Raya's `chats_visible_to` query stop matching this Chat
    AT ALL — not just hiding the new Kasongan-period messages (the
    intended, already-working behavior — see `ChatMessagesView`'s own
    per-Office message filter) but losing the Chat, and therefore its own
    already-tagged Palangka Raya history, outright. Discussed requirement:
    that history must stay Palangka Raya's forever, just never bleed into
    Kasongan's — this is the other half of that same guarantee.
    `.distinct()` because the `messages__office` join can otherwise
    return the same Chat once per matching Message row."""
    from .models import Chat

    if has_global_access(user):
        return Chat.objects.all()

    office = get_user_office(user)
    if office is None:
        return Chat.objects.none()
    return Chat.objects.filter(Q(office=office) | Q(messages__office=office)).distinct()


def can_view_chat(user, chat) -> bool:
    """Object-level equivalent of `chats_visible_to` — same rule, for a
    single already-fetched chat (messages/mark-read), so there is exactly
    one rule, not two. Use `can_manage_chat` instead for any endpoint that
    MUTATES operator-routing state — see that function's own docstring
    for why the two must not be conflated."""
    return chats_visible_to(user).filter(pk=chat.pk).exists()


def can_manage_chat(user, chat) -> bool:
    """Stricter than `can_view_chat` — whether `user` may MUTATE this
    Chat's operator-routing state (assign/unassign/claim/close-session/
    list assignment candidates). Deliberately requires the Chat's
    CURRENT `office` to match (the original, pre-history-fix rule)
    — `chats_visible_to`/`can_view_chat` were broadened to also show a
    Chat to an Office that no longer currently owns it, so that Office's
    own past message history stays visible (found live: Palangka Raya's
    own history disappeared entirely once a citizen re-selected Kasongan
    for a new round). That broadening must never extend to letting
    Palangka Raya act on a case that has since moved to Kasongan — e.g.
    closing Kasongan's now-active WAITING_OPERATOR session. Superadmin/
    Global Admin unaffected either way."""
    if has_global_access(user):
        return True
    office = get_user_office(user)
    return office is not None and chat.office_id == office.pk
