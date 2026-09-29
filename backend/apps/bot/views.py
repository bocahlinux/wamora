"""Conversation/Bot Engine — admin CRUD API. Mounted at `/api/bot/`,
frontend-facing (JWTAuthentication), same trust boundary as
`apps.offices.views`/`apps.blast.views` (a logged-in human's browser).

Authorization: Superadmin/Global Admin ONLY, for every resource this
module owns (`BotConfig`, `BotMenu`, `BotMenuItem`, `BotTrigger`),
regardless of `?office=`/body `office`. Revised per explicit discussion
(docs/generated — bot menu/trigger content decided by superadmin only):
an Office Admin creating its own menu/trigger content is what caused a
live bug (a half-configured, disabled per-Office `BotConfig` silently
shadowing the enabled GLOBAL one for every Chat routed to that Office —
see `BotConfigView.get()`'s own docstring) and fragments what should be
ONE shared bot across every Office. `apps.offices.models.OfficeInboxConfig.enabled`
(via `apps.offices.views.OfficeInboxConfigView`, unaffected by this
module) remains the one thing an Office Admin may still toggle:
"does my Office accept a direct handoff to a human operator" — a
separate, pre-existing concern this module never touches."""

from django.db.models import ProtectedError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasUserAdministrationScope
from apps.offices.authorization import has_global_access
from apps.offices.models import Office

from .models import BotConfig, BotMenu, BotMenuItem, BotTrigger
from .serializers import BotConfigSerializer, BotMenuItemSerializer, BotMenuSerializer, BotTriggerSerializer


def _error(request, http_status, code, message):
    request_id = getattr(request, 'request_id', None)
    return Response({'error': {'code': code, 'message': message, 'request_id': request_id}}, status=http_status)


def _may_access(user, office):
    """Superadmin/Global Admin only — `office` is accepted (and still
    validated by `_resolve_office_param`/the serializer) purely so an
    invalid id still 400s before this check runs; it no longer grants an
    Office Admin access to their own Office's bot content."""
    return has_global_access(user)


def _resolve_office_param(request):
    """`?office=<id>` query param -> `Office` instance, or `None` if
    absent (meaning: the GLOBAL resource). Raises via return of
    `(None, error_response)` if the id doesn't resolve to a real Office."""
    raw = request.query_params.get('office')
    if not raw:
        return None, None
    try:
        return Office.objects.get(pk=raw), None
    except (Office.DoesNotExist, ValueError, TypeError):
        return None, _error(request, 400, 'invalid', 'office does not reference a real Office.')


class BotConfigView(APIView):
    """GET/PATCH /api/bot/config/?office=<id> — omit `office` for the
    GLOBAL config (lazy `get_or_create(office=None)`, same pattern
    `OfficeInboxConfigView` already uses per-Office)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _resolve(self, request):
        office, error = _resolve_office_param(request)
        if error is not None:
            return None, error
        if not _may_access(request.user, office):
            return None, _error(request, 403, 'forbidden', 'You do not have access to this Bot configuration.')
        return office, None

    def get(self, request):
        """Read-only — deliberately does NOT persist a row (unlike the
        `OfficeInboxConfig` lazy-singleton precedent this class's own
        docstring cites): an admin merely opening this Office's Bot
        Configuration tab must never create a real, DB-durable
        `enabled=False` override that then silently shadows the GLOBAL
        config for every Chat already routed to that Office (found live:
        an inbound WhatsApp message went unanswered purely because a
        prior GET had persisted such a row). An unsaved, in-memory
        default (`id=None`) is returned instead when no row exists yet —
        a real row is only ever created by `patch()`, an explicit admin
        save."""
        office, error = self._resolve(request)
        if error is not None:
            return error
        config = BotConfig.objects.filter(office=office).first() or BotConfig(office=office)
        return Response(BotConfigSerializer(config).data)

    def patch(self, request):
        office, error = self._resolve(request)
        if error is not None:
            return error
        config, _created = BotConfig.objects.get_or_create(office=office)
        serializer = BotConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(BotConfigSerializer(config).data)


class BotMenuListCreateView(APIView):
    """GET /api/bot/menus/?office=<id> — list menus for that Office, or
    GLOBAL menus if `office` is omitted. POST /api/bot/menus/ — create;
    body's own `office` field decides scope (validated against the same
    `_may_access` rule, so a client can't create a menu in an Office it
    doesn't administer merely by putting a different id in the body)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request):
        office, error = _resolve_office_param(request)
        if error is not None:
            return error
        if not _may_access(request.user, office):
            return _error(request, 403, 'forbidden', 'You do not have access to these Bot menus.')
        menus = BotMenu.objects.filter(office=office).order_by('name')
        return Response(BotMenuSerializer(menus, many=True).data)

    def post(self, request):
        serializer = BotMenuSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        office = serializer.validated_data.get('office')
        if not _may_access(request.user, office):
            return _error(request, 403, 'forbidden', 'You do not have access to create a menu in this scope.')
        menu = serializer.save()
        return Response(BotMenuSerializer(menu).data, status=201)


class BotMenuDetailView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request, pk):
        try:
            menu = BotMenu.objects.get(pk=pk)
        except BotMenu.DoesNotExist:
            return _error(request, 404, 'not_found', 'Menu not found.')
        if not _may_access(request.user, menu.office):
            return _error(request, 403, 'forbidden', 'You do not have access to this menu.')
        return Response(BotMenuSerializer(menu).data)

    def patch(self, request, pk):
        try:
            menu = BotMenu.objects.get(pk=pk)
        except BotMenu.DoesNotExist:
            return _error(request, 404, 'not_found', 'Menu not found.')
        if not _may_access(request.user, menu.office):
            return _error(request, 403, 'forbidden', 'You do not have access to this menu.')
        serializer = BotMenuSerializer(menu, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # A PATCH changing `office` must be re-checked against the NEW
        # office too — never trust the pre-save value alone.
        new_office = serializer.validated_data.get('office', menu.office)
        if not _may_access(request.user, new_office):
            return _error(request, 403, 'forbidden', 'You do not have access to move this menu to that scope.')
        serializer.save()
        return Response(BotMenuSerializer(menu).data)

    def delete(self, request, pk):
        try:
            menu = BotMenu.objects.get(pk=pk)
        except BotMenu.DoesNotExist:
            return _error(request, 404, 'not_found', 'Menu not found.')
        if not _may_access(request.user, menu.office):
            return _error(request, 403, 'forbidden', 'You do not have access to this menu.')
        try:
            menu.delete()
        except ProtectedError:
            return _error(
                request, 400, 'invalid',
                'This menu is referenced by a menu item, trigger, bot config, or in-progress conversation — '
                'reassign or remove those first.',
            )
        return Response({'deleted': True})


class BotMenuItemListCreateView(APIView):
    """GET /api/bot/menus/<menu_pk>/items/ — list. POST — create within
    that menu (scope always inherited from the parent menu, never
    independently settable)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _get_menu(self, request, menu_pk):
        try:
            menu = BotMenu.objects.get(pk=menu_pk)
        except BotMenu.DoesNotExist:
            return None, _error(request, 404, 'not_found', 'Menu not found.')
        if not _may_access(request.user, menu.office):
            return None, _error(request, 403, 'forbidden', 'You do not have access to this menu.')
        return menu, None

    def get(self, request, menu_pk):
        menu, error = self._get_menu(request, menu_pk)
        if error is not None:
            return error
        return Response(BotMenuItemSerializer(menu.items.all(), many=True).data)

    def post(self, request, menu_pk):
        menu, error = self._get_menu(request, menu_pk)
        if error is not None:
            return error
        data = dict(request.data)
        data['menu'] = menu.pk
        serializer = BotMenuItemSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return Response(BotMenuItemSerializer(item).data, status=201)


class BotMenuItemDetailView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _get_item(self, request, pk):
        try:
            item = BotMenuItem.objects.select_related('menu').get(pk=pk)
        except BotMenuItem.DoesNotExist:
            return None, _error(request, 404, 'not_found', 'Menu item not found.')
        if not _may_access(request.user, item.menu.office):
            return None, _error(request, 403, 'forbidden', 'You do not have access to this menu item.')
        return item, None

    def patch(self, request, pk):
        item, error = self._get_item(request, pk)
        if error is not None:
            return error
        data = dict(request.data)
        data.pop('menu', None)  # never movable to a different menu via this endpoint
        serializer = BotMenuItemSerializer(item, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(BotMenuItemSerializer(item).data)

    def delete(self, request, pk):
        item, error = self._get_item(request, pk)
        if error is not None:
            return error
        item.delete()
        return Response({'deleted': True})


class BotTriggerListCreateView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request):
        office, error = _resolve_office_param(request)
        if error is not None:
            return error
        if not _may_access(request.user, office):
            return _error(request, 403, 'forbidden', 'You do not have access to these triggers.')
        triggers = BotTrigger.objects.filter(office=office).order_by('keyword')
        return Response(BotTriggerSerializer(triggers, many=True).data)

    def post(self, request):
        serializer = BotTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        office = serializer.validated_data.get('office')
        if not _may_access(request.user, office):
            return _error(request, 403, 'forbidden', 'You do not have access to create a trigger in this scope.')
        trigger = serializer.save()
        return Response(BotTriggerSerializer(trigger).data, status=201)


class BotTriggerDetailView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _get_trigger(self, request, pk):
        try:
            trigger = BotTrigger.objects.get(pk=pk)
        except BotTrigger.DoesNotExist:
            return None, _error(request, 404, 'not_found', 'Trigger not found.')
        if not _may_access(request.user, trigger.office):
            return None, _error(request, 403, 'forbidden', 'You do not have access to this trigger.')
        return trigger, None

    def patch(self, request, pk):
        trigger, error = self._get_trigger(request, pk)
        if error is not None:
            return error
        serializer = BotTriggerSerializer(trigger, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_office = serializer.validated_data.get('office', trigger.office)
        if not _may_access(request.user, new_office):
            return _error(request, 403, 'forbidden', 'You do not have access to move this trigger to that scope.')
        serializer.save()
        return Response(BotTriggerSerializer(trigger).data)

    def delete(self, request, pk):
        trigger, error = self._get_trigger(request, pk)
        if error is not None:
            return error
        trigger.delete()
        return Response({'deleted': True})
