"""Office & User management — Step 6. Frontend-facing (JWTAuthentication),
mounted at `/api/offices/` and `/api/users/` — same trust boundary as
`apps.blast.views`/`apps.chats.views` (a logged-in human's browser, not
BFF/Celery-internal traffic).

Every view here is gated by `HasUserAdministrationScope` (the technical
JWT-scope check) AND `_admin_scope()` below (the organizational-fact
check, built entirely from `apps.offices.authorization` — never
re-derived). Both must pass; scope alone is not enough for an Office
Admin who has been removed from their Office, and org-fact access alone
is not enough for a Superadmin whose token predates any scope change —
though in practice a superuser always has every scope already.
"""

from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasUserAdministrationScope

from .authorization import has_global_access, is_office_admin_role, is_operator_role
from .models import Office, OfficeInboxConfig, OfficeMembership, Role, UserProfile
from .serializers import (
    MembershipUpdateSerializer,
    MyProfileUpdateSerializer,
    OfficeInboxConfigSerializer,
    OfficeSerializer,
    OperatorAvailabilitySerializer,
    RoleSerializer,
    UserCreateSerializer,
    UserProfileUpdateSerializer,
    UserSerializer,
    _sync_role_groups,
)


def _error(request, http_status, code, message):
    request_id = getattr(request, 'request_id', None)
    return Response({'error': {'code': code, 'message': message, 'request_id': request_id}}, status=http_status)


def _admin_scope(user):
    """`'global'` for Superadmin/Global Admin (may manage every Office/
    user), the user's own `Office` for an Office Admin (may manage only
    that Office's users — never Offices themselves), or `None` for
    anyone else (Operator, or no membership at all) — no administration
    access whatsoever."""
    if has_global_access(user):
        return 'global'
    if is_office_admin_role(user):
        return user.office_membership.office
    return None


class OfficeListCreateView(APIView):
    """GET /api/offices/ — list every Office (active and inactive).
    POST /api/offices/ — create an Office.

    Office Admin never reaches either: Office Admin manages users
    *within* their Office, never Offices themselves (Step 6 Bagian B/D)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a globally-accessing administrator may manage Offices.')
        offices = Office.objects.all().order_by('name')
        return Response(OfficeSerializer(offices, many=True).data)

    def post(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a globally-accessing administrator may manage Offices.')
        serializer = OfficeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        office = serializer.save()
        AuditLog.objects.create(
            actor=request.user, action='office.create', target=office.name, result=AuditLog.RESULT_SUCCESS
        )
        return Response(OfficeSerializer(office).data, status=201)


class OfficeDetailView(APIView):
    """GET /api/offices/<pk>/ — detail. PATCH /api/offices/<pk>/ — update
    name/is_active (activate/deactivate is just `is_active` via this same
    PATCH — no separate endpoint, matching this repository's existing
    economy of endpoints, e.g. Blast's mark-as-read reusing PATCH-shaped
    single-purpose views rather than a dedicated action per state)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request, pk):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a globally-accessing administrator may manage Offices.')
        office = get_object_or_404(Office, pk=pk)
        return Response(OfficeSerializer(office).data)

    def patch(self, request, pk):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a globally-accessing administrator may manage Offices.')
        office = get_object_or_404(Office, pk=pk)
        serializer = OfficeSerializer(office, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.objects.create(
            actor=request.user, action='office.update', target=office.name, result=AuditLog.RESULT_SUCCESS
        )
        return Response(OfficeSerializer(office).data)


class OfficeInboxConfigView(APIView):
    """GET/PATCH /api/offices/<pk>/inbox-config/ — Step 10 foundation.
    Reuses `_admin_scope()` (same helper as every other view in this
    module) — no new role-checking logic: Superadmin/Global Admin reach
    any Office, an Office Admin only their own, Operator/no-membership
    get 403. Read-only for now beyond storage: nothing here sends a
    message or feeds any WhatsApp flow.

    The config row is created LAZILY on first GET/PATCH
    (`get_or_create`) — no data migration backfilled one for existing
    Offices, so a never-configured Office simply reports the model's own
    safe defaults (`enabled=False`, empty messages) until an admin saves
    something real."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _get_office(self, request, pk):
        scope = _admin_scope(request.user)
        if scope is None:
            return None, _error(request, 403, 'forbidden', 'You do not have administration access.')
        office = get_object_or_404(Office, pk=pk)
        if scope != 'global' and office.pk != scope.pk:
            return None, _error(request, 403, 'forbidden', 'You do not have access to this Office.')
        return office, None

    def get(self, request, pk):
        office, error = self._get_office(request, pk)
        if error is not None:
            return error
        config, _created = OfficeInboxConfig.objects.get_or_create(office=office)
        return Response(OfficeInboxConfigSerializer(config).data)

    def patch(self, request, pk):
        office, error = self._get_office(request, pk)
        if error is not None:
            return error
        config, _created = OfficeInboxConfig.objects.get_or_create(office=office)
        serializer = OfficeInboxConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.objects.create(
            actor=request.user, action='office.inbox_config.update', target=office.name, result=AuditLog.RESULT_SUCCESS
        )
        return Response(OfficeInboxConfigSerializer(config).data)


class RoleListCreateView(APIView):
    """GET /api/roles/ — readable by any actor with administration access
    at all (`_admin_scope(request.user) is not None` — Superuser, Global
    Admin, OR Office Admin), so the Users form's single `role` picker
    (`UserDetailView`/`UserCreateSerializer`) has a real catalog to
    choose from regardless of who's creating/editing the user — an Office
    Admin can still only ever WRITE a non-`grants_global_access` Role
    (enforced separately in `UserListCreateView.post`/
    `UserDetailView.patch`), but they need to be able to SEE the Role
    catalog to make that choice at all; the old fixed 3-value enum never
    needed an API call for this, but a dynamic Role does. POST
    /api/roles/ — Superuser-only:
    *defining* what a Role grants must never be reachable by a
    non-superuser, not even a Global Admin who holds `user
    administration` themselves (via their own assigned Role) — otherwise
    a Global Admin could mint themselves a Role containing a scope they
    don't already have (e.g. `system administration`), the exact
    self-escalation every other check in `apps.authn.permissions` already
    guards against. Deliberately checks `request.user.is_superuser`
    directly rather than a permission class — `is_superuser` was never
    put in the JWT itself, and GET/POST need different authorization on
    the same view (same "coarse `permission_classes` gate + fine-grained
    per-method check" shape `OfficeListCreateView` above already uses)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if _admin_scope(request.user) is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        roles = Role.objects.all().order_by('name')
        return Response(RoleSerializer(roles, many=True).data)

    def post(self, request):
        if not request.user.is_superuser:
            return _error(request, 403, 'forbidden', 'Only a Superadmin may create a Role.')
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        AuditLog.objects.create(actor=request.user, action='role.create', target=role.name, result=AuditLog.RESULT_SUCCESS)
        return Response(RoleSerializer(role).data, status=201)


class RoleDetailView(APIView):
    """GET /api/roles/<pk>/ — same admin-access read rule as the list
    view above. PATCH/DELETE — Superuser-only, same reasoning as
    `RoleListCreateView.post`. DELETE is blocked (400, not a raw 500)
    while any `OfficeMembership` still points at this Role
    (`on_delete=PROTECT` on `OfficeMembership.role`) — a Superadmin must
    reassign every affected user to a different Role first (every
    membership requires one), same "explicit, deliberate action"
    convention as every other PROTECTed FK in this app."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if _admin_scope(request.user) is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        role = get_object_or_404(Role, pk=pk)
        return Response(RoleSerializer(role).data)

    def patch(self, request, pk):
        if not request.user.is_superuser:
            return _error(request, 403, 'forbidden', 'Only a Superadmin may edit a Role.')
        role = get_object_or_404(Role, pk=pk)
        serializer = RoleSerializer(role, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        AuditLog.objects.create(actor=request.user, action='role.update', target=role.name, result=AuditLog.RESULT_SUCCESS)
        # Re-sync every currently-assigned member's Groups immediately —
        # otherwise an edit to an in-use Role's scopes would only take
        # effect the next time each affected user's own membership was
        # separately saved, which is surprising for what looks like a
        # single, immediate admin action.
        for membership in role.memberships.select_related('user').all():
            _sync_role_groups(membership.user, role)
        return Response(RoleSerializer(role).data)

    def delete(self, request, pk):
        if not request.user.is_superuser:
            return _error(request, 403, 'forbidden', 'Only a Superadmin may delete a Role.')
        role = get_object_or_404(Role, pk=pk)
        try:
            role.delete()
        except ProtectedError:
            count = role.memberships.count()
            return _error(
                request, 400, 'invalid',
                f'This Role is assigned to {count} user(s) — reassign or clear it from them first.',
            )
        AuditLog.objects.create(actor=request.user, action='role.delete', target=role.name, result=AuditLog.RESULT_SUCCESS)
        # A 200 with a small JSON body, not a bare 204 — frontend/src/lib/
        # api.ts's request() treats an empty-bodied 2xx as an unparseable
        # `kind: 'unknown'` error (it expects every successful response to
        # carry JSON), matching every other endpoint in this API.
        return Response({'deleted': True})


def _users_queryset():
    return User.objects.select_related(
        'office_membership', 'office_membership__office', 'office_membership__role', 'profile',
    )


class UserListCreateView(APIView):
    """GET /api/users/ — list users visible to the caller's admin scope
    (every user for Superadmin/Global Admin, only the caller's own
    Office's users for an Office Admin). POST /api/users/ — create a
    user plus its OfficeMembership in one call; never creates a
    Superadmin (`is_superuser` is not a field this API exposes at all —
    that stays a Django-only action)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def get(self, request):
        scope = _admin_scope(request.user)
        if scope is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        users = _users_queryset()
        if scope != 'global':
            users = users.filter(office_membership__office=scope)
        return Response(UserSerializer(users.order_by('username'), many=True).data)

    def post(self, request):
        scope = _admin_scope(request.user)
        if scope is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        serializer = UserCreateSerializer(data=request.data, context={'actor_scope': scope})
        serializer.is_valid(raise_exception=True)
        # Checked AFTER validation (not against the raw request body) so
        # this always reads the real Role's flag, never a client-supplied
        # id that happens to look right — same "only a globally-accessing
        # actor may create a Global Admin"-equivalent guard as before this
        # merge, now keyed off `role.grants_global_access` instead of
        # comparing to the old fixed string. An Office Admin creating
        # another Office-Admin-equivalent or Operator-equivalent Role
        # within their own Office is unaffected, same as before.
        if scope != 'global' and serializer.validated_data['role'].grants_global_access:
            return _error(
                request, 403, 'forbidden',
                'Only a globally-accessing administrator may assign a Role with global access.',
            )
        user = serializer.save()
        AuditLog.objects.create(
            actor=request.user, action='user.create', target=user.username, result=AuditLog.RESULT_SUCCESS
        )
        return Response(UserSerializer(user).data, status=201)


class UserDetailView(APIView):
    """GET /api/users/<pk>/ — detail, same visibility rule as the list.
    PATCH /api/users/<pk>/ — profile fields (first_name/last_name/
    is_active/password) and/or role+office (both together), subject to
    the same scope rule as create. A non-Superadmin admin may never
    target their own row here (Step 6 Bagian D rule 8 — no
    self-escalation path; Superadmin is exempt, per rule 10, and has no
    membership row for role/office to escalate anyway)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasUserAdministrationScope]

    def _get_target(self, request, scope, pk):
        target = get_object_or_404(_users_queryset(), pk=pk)
        if scope != 'global':
            membership = getattr(target, 'office_membership', None)
            if membership is None or membership.office_id != scope.pk:
                return None
        return target

    def get(self, request, pk):
        scope = _admin_scope(request.user)
        if scope is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        target = self._get_target(request, scope, pk)
        if target is None:
            return _error(request, 403, 'forbidden', 'You do not have access to this user.')
        return Response(UserSerializer(target).data)

    def patch(self, request, pk):
        scope = _admin_scope(request.user)
        if scope is None:
            return _error(request, 403, 'forbidden', 'You do not have administration access.')
        target = self._get_target(request, scope, pk)
        if target is None:
            return _error(request, 403, 'forbidden', 'You do not have access to this user.')
        if target.pk == request.user.pk and not request.user.is_superuser:
            return _error(request, 403, 'forbidden', 'You cannot manage your own account through this endpoint.')

        data = request.data
        has_role = 'role' in data
        has_office = 'office' in data
        if has_role != has_office:
            return _error(request, 400, 'invalid', 'role and office must be provided together.')

        profile_serializer = UserProfileUpdateSerializer(data=data, partial=True)
        profile_serializer.is_valid(raise_exception=True)
        new_initial = None
        for field, value in profile_serializer.validated_data.items():
            if field == 'password':
                target.set_password(value)
            elif field == 'initial':
                # apps.offices.models.UserProfile, not a User field —
                # applied after target.save() below, via get_or_create
                # (a user created before UserProfile existed has none yet).
                new_initial = value
            else:
                setattr(target, field, value)
        target.save()
        if new_initial is not None:
            UserProfile.objects.update_or_create(user=target, defaults={'initial': new_initial})

        if has_role and target.is_superuser:
            return _error(
                request, 400, 'invalid', 'Superuser accounts are not managed via Office role assignment.'
            )

        if has_role:
            membership_serializer = MembershipUpdateSerializer(data=data)
            membership_serializer.is_valid(raise_exception=True)
            role = membership_serializer.validated_data['role']
            office = membership_serializer.validated_data.get('office')
            if scope != 'global':
                if role.grants_global_access:
                    return _error(
                        request, 403, 'forbidden',
                        'Only a globally-accessing administrator may assign a Role with global access.',
                    )
                if office is None or office.pk != scope.pk:
                    return _error(request, 403, 'forbidden', 'An Office Admin cannot move a user to another Office.')
            OfficeMembership.objects.update_or_create(
                user=target,
                defaults={'role': role, 'office': office, 'requires_office': not role.grants_global_access},
            )
            _sync_role_groups(target, role)

        AuditLog.objects.create(
            actor=request.user, action='user.update', target=target.username, result=AuditLog.RESULT_SUCCESS
        )
        # Re-fetch rather than trust the in-memory instance's cached
        # reverse-OneToOne accessor after the membership write above.
        target = _users_queryset().get(pk=target.pk)
        return Response(UserSerializer(target).data)


class OperatorAvailabilityView(APIView):
    """PATCH /api/auth/me/availability/ — Step 14. Self-service only:
    always `request.user`'s own `OfficeMembership`, never a target `pk`
    in the URL, so there is no "which user" input to validate at all —
    an Office Admin/Global Admin/Superadmin cannot use this to change
    someone ELSE's availability (Step 14 Section 11's own explicit
    rule); they would need the existing `UserDetailView` role/office
    PATCH for that, which this deliberately does not touch or duplicate.
    Only a membership whose Role carries `is_operator` may use this
    endpoint — matches `apps.chats.assignment.valid_assignment_candidates`'s
    own `role__is_operator=True`-only scope, so this field only ever
    means something for the same rows that field is read from."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        membership = getattr(request.user, 'office_membership', None)
        if membership is None or not is_operator_role(request.user):
            return _error(request, 403, 'forbidden', 'Only an Operator may set their own availability.')

        serializer = OperatorAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership.is_available = serializer.validated_data['is_available']
        membership.save(update_fields=['is_available', 'updated_at'])
        return Response({'is_available': membership.is_available})


def _profile_payload(user):
    profile = getattr(user, 'profile', None)
    return {
        'id': user.pk,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'initial': profile.initial if profile else '',
    }


class MyProfileView(APIView):
    """GET/PATCH /api/auth/me/profile/ — discussed requirement: every
    role (Superadmin/Global Admin/Office Admin/Operator alike) may view
    and edit their OWN name/initial/password. Self-service only, same
    "always request.user's own row, never a target pk" shape as
    `OperatorAvailabilityView` right above — no admin scope required,
    just authentication.

    `username` is deliberately never editable here (or anywhere in this
    API) — it stays the stable identifier `UserCreateSerializer`'s
    uniqueness/character-set rules were validated against at creation."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_profile_payload(request.user))

    def patch(self, request):
        serializer = MyProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if 'new_password' in data:
            if not request.user.check_password(data['current_password']):
                return _error(request, 400, 'invalid_password', 'Your current password is incorrect.')
            request.user.set_password(data['new_password'])

        if 'first_name' in data:
            request.user.first_name = data['first_name']
        if 'last_name' in data:
            request.user.last_name = data['last_name']
        request.user.save()

        if 'initial' in data:
            UserProfile.objects.update_or_create(user=request.user, defaults={'initial': data['initial']})

        AuditLog.objects.create(
            actor=request.user, action='user.self_update', target=request.user.username,
            result=AuditLog.RESULT_SUCCESS,
        )
        request.user.refresh_from_db()
        return Response(_profile_payload(request.user))
