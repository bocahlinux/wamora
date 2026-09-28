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

from apps.offices.authorization import get_user_office, has_global_access


def chats_visible_to(user):
    """The `Chat` queryset `user` may see/act on."""
    from .models import Chat

    if has_global_access(user):
        return Chat.objects.all()

    office = get_user_office(user)
    if office is None:
        return Chat.objects.none()
    return Chat.objects.filter(office=office)


def can_view_chat(user, chat) -> bool:
    """Object-level equivalent of `chats_visible_to` — same rule, for a
    single already-fetched chat (messages/mark-read), so there is exactly
    one rule, not two."""
    return chats_visible_to(user).filter(pk=chat.pk).exists()
