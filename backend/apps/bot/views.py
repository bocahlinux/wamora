"""Conversation/Bot Engine — admin CRUD API. Mounted at `/api/bot/`,
frontend-facing (JWTAuthentication), same trust boundary as
`apps.offices.views`/`apps.blast.views` (a logged-in human's browser).

Authorization reuses `apps.offices.authorization` directly — no new
primitive invented, per the approved design's explicit instruction
("Gunakan pola authorization existing sebagai dasar desain"):
- A GLOBAL resource (`office=None` — the shared Main Menu, global
  triggers, the GLOBAL `BotConfig`) may only be read/written by a
  globally-accessing actor (Superadmin/Global Admin) — an Office Admin
  editing the GLOBAL Main Menu would affect every other Office, the same
  class of reasoning `apps.offices.views.OfficeListCreateView` already
  applies to Offices themselves.
- An Office-scoped resource follows the same `_admin_scope()`-equivalent
  rule `OfficeInboxConfigView` already uses: Superadmin/Global Admin
  reach any Office; an Office Admin only their own; Operator/no-membership
  get 403.
"""

from django.db.models import ProtectedError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasUserAdministrationScope
from apps.offices.authorization import get_user_office, has_global_access, is_office_admin_role
from apps.offices.models import Office

from .models import BotConfig, BotMenu, BotMenuItem, BotTrigger
from .serializers import BotConfigSerializer, BotMenuItemSerializer, BotMenuSerializer, BotTriggerSerializer


def _error(request, http_status, code, message):
    request_id = getattr(request, 'request_id', None)
    return Response({'error': {'code': code, 'message': message, 'request_id': request_id}}, status=http_status)


def _may_access(user, office):
    """`office=None` (GLOBAL resource) — only a globally-accessing actor.
    `office` given — globally-accessing actor (any Office) or an Office
    Admin of exactly that Office. Mirrors `apps.offices.views._admin_scope()`
    without importing it directly (that helper is private to that module) —
    same three functions (`has_global_access`/`is_office_admin_role`/
    `get_user_office`) it's itself built from."""
    if has_global_access(user):
        return True
    if office is None:
        return False
    return is_office_admin_role(user) and get_user_office(user) is not None and get_user_office(user).pk == office.pk


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

    def _get_or_create(self, request):
        office, error = _resolve_office_param(request)
        if error is not None:
            return None, error
        if not _may_access(request.user, office):
            return None, _error(request, 403, 'forbidden', 'You do not have access to this Bot configuration.')
        config, _created = BotConfig.objects.get_or_create(office=office)
        return config, None

    def get(self, request):
        config, error = self._get_or_create(request)
        if error is not None:
            return error
        return Response(BotConfigSerializer(config).data)

    def patch(self, request):
        config, error = self._get_or_create(request)
        if error is not None:
            return error
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
