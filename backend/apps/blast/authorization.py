"""Blast <-> Office boundary — Step 4. The single place this rule lives;
every Blast view (list/detail/submit/approve/reject/resolve) filters or
checks through `campaigns_visible_to`/`can_view_campaign`, never
re-deriving `is_superuser`/role/office comparison itself.

Built entirely from `apps.offices.authorization`'s existing primitives
(`has_global_access`, `get_user_office`) — no new office/role logic is
introduced here, only Blast-specific composition.

A campaign with `office=None` (created before this Office boundary
existed — see `apps.blast.models.BlastCampaign.office`'s own comment)
is deliberately visible under the exact rule that applied before this
step: to anyone with the right scope who has no Office membership of
their own. Once a user has a real Office (Office Admin/Operator), they
see only that Office's campaigns — never a legacy/office-less one,
matching the "hanya Office miliknya" requirement precisely. This is
what keeps every pre-Step-4 test and the 5 real pre-existing campaigns
working unchanged, while still enforcing a real boundary for anything
newly created with a real Office.
"""

from apps.offices.authorization import get_user_office, has_global_access


def campaigns_visible_to(user):
    """The `BlastCampaign` queryset `user` may see/act on."""
    from .models import BlastCampaign

    if has_global_access(user):
        return BlastCampaign.objects.all()

    office = get_user_office(user)
    if office is None:
        return BlastCampaign.objects.filter(office__isnull=True)
    return BlastCampaign.objects.filter(office=office)


def can_view_campaign(user, campaign) -> bool:
    """Object-level equivalent of `campaigns_visible_to` — same rule,
    for a single already-fetched campaign (detail/submit/approve/
    reject/resolve), so there is exactly one rule, not two."""
    return campaigns_visible_to(user).filter(pk=campaign.pk).exists()


def templates_visible_to(user):
    """Same office-boundary shape as `campaigns_visible_to`, for
    `BlastTemplate`: a globally-accessing user sees every template; an
    Office-bound user sees their own Office's templates PLUS every
    global (`office__isnull=True`) template, since a global template is
    explicitly meant to be shared/reused by every Office (see
    `BlastTemplate.office`'s own docstring)."""
    from django.db.models import Q

    from .models import BlastTemplate

    if has_global_access(user):
        return BlastTemplate.objects.all()

    office = get_user_office(user)
    if office is None:
        return BlastTemplate.objects.filter(office__isnull=True)
    return BlastTemplate.objects.filter(Q(office=office) | Q(office__isnull=True))


def can_view_template(user, template) -> bool:
    return templates_visible_to(user).filter(pk=template.pk).exists()
