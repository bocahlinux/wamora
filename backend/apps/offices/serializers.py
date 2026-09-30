"""Office & User management — Step 6. Plain serializers over the existing
`Office`/`OfficeMembership` models and the stock
`django.contrib.auth.models.User` — no custom User model.

Step 6 originally also decided against a Role/Permission model; that
decision is deliberately revisited by the `Role` model (a later, explicit
request to make menu/feature access AND organizational standing
Superadmin-editable rather than hardcoded, fully merging what used to be
two separate fields into one) — see `Role`'s own docstring in
`models.py`.

Authorization ("who is allowed to see/create/edit what") is deliberately
NOT here — it lives entirely in `views.py`, built from
`apps.offices.authorization`, exactly like `apps.blast`'s own
authorization.py/views.py split. `validate()` below only encodes DATA
validity (the same office_matches_role rule `OfficeMembership`'s own
CheckConstraint enforces at the DB level, checked here first so a bad
combination is a clean 400, not an IntegrityError) plus the one piece of
actor-aware forcing that has direct precedent in
`apps.blast.serializers.BlastCampaignCreateSerializer.validate()`: an
Office-scoped actor (Office Admin) can never place a user outside their
own Office, no matter what the client sends — "jangan mempercayai Office
arbitrary dari client" applies here exactly as it did for Blast.
"""

import re

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import transaction
from rest_framework import serializers

from .menu_items import MENU_ITEM_KEYS
from .models import Office, OfficeInboxConfig, OfficeMembership, Role, UserProfile

# Discussed requirement — username creation rule (Superadmin/Global
# Admin/Office Admin, UserCreateSerializer below): letters (either case),
# digits, dot (.), underscore (_) only. Nothing else — no spaces, no other
# punctuation. Django's own default `User.username` validator is far more
# permissive (allows @+-), so this is checked explicitly, not inherited.
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9._]+$')
USERNAME_RULE_MESSAGE = (
    'username may only contain letters, numbers, dot (.) and underscore (_).'
)

# `_sync_role_groups` replaces the previous hardcoded `ROLE_GROUPS`
# mapping (Global/Office Admin -> a fixed ('user administration', 'blast',
# 'reading') bundle): a user's actual scope-Groups are now driven entirely
# by whatever `Role` their `OfficeMembership.role` points at — a
# Superadmin-editable replacement for what used to require a code change.
# `settings.JWT_SCOPES` is still the fixed, already-enforced vocabulary
# (`RoleSerializer.validate_scopes` below rejects anything outside it) —
# this only changes WHO decides which of those 6 scopes a given user's
# account carries, from a code constant to a `Role` row. Organizational
# standing (`role.grants_global_access`/`.is_office_admin`/`.is_operator`)
# is a separate concern, read only by `apps.offices.authorization` — this
# function only ever touches scope-Groups.
def _sync_role_groups(user, role):
    wanted = set(role.scopes) if role is not None else set()
    for name in settings.JWT_SCOPES:
        group, _ = Group.objects.get_or_create(name=name)
        if name in wanted:
            user.groups.add(group)
        else:
            user.groups.remove(group)


def _validate_role_office(role, office):
    """Mirrors `OfficeMembership`'s own `office_matches_role`
    CheckConstraint (via the denormalized `requires_office` — see that
    field's own comment in models.py) — checked here so a bad combination
    surfaces as a normal 400, not a raw IntegrityError."""
    if role.grants_global_access and office is not None:
        raise serializers.ValidationError({'office': 'A globally-accessing Role must not have an Office.'})
    if not role.grants_global_access and office is None:
        raise serializers.ValidationError({'office': 'This Role requires an Office.'})


class OfficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Office
        fields = ['id', 'name', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('name must not be blank.')
        return value


class RoleSerializer(serializers.ModelSerializer):
    """CRUD shape for `Role` — reachable only via `IsSuperuser`-gated
    views (`RoleListCreateView`/`RoleDetailView`), never via a scope, so
    defining what a Role can grant — both `scopes` (feature/menu access)
    AND `grants_global_access`/`is_office_admin`/`is_operator`
    (organizational standing, the Role merge) — is never itself reachable
    by someone who only holds a scope."""

    class Meta:
        model = Role
        fields = [
            'id', 'name', 'scopes', 'grants_global_access', 'is_office_admin', 'is_operator',
            'visible_menu_items', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('name must not be blank.')
        return value

    def validate_scopes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('scopes must be a list.')
        unknown = sorted(set(value) - set(settings.JWT_SCOPES))
        if unknown:
            raise serializers.ValidationError(f'Unknown scope(s): {", ".join(unknown)}.')
        # De-duplicated but order-preserving — a client resubmitting the
        # same set twice (e.g. a checkbox form) never grows the list.
        seen = []
        for scope in value:
            if scope not in seen:
                seen.append(scope)
        return seen

    def validate_visible_menu_items(self, value):
        # Discussed requirement — Menu Access. `None` ("not customized,
        # fall back to scope-based visibility" — Role's own docstring) is
        # passed through as-is; `[]` (deliberately "show nothing") and
        # any non-empty list are validated against the fixed
        # MENU_ITEM_KEYS vocabulary, same discipline validate_scopes
        # already applies to `scopes` — never a freeform value.
        if value is None:
            return None
        if not isinstance(value, list):
            raise serializers.ValidationError('visible_menu_items must be a list or null.')
        unknown = sorted(set(value) - set(MENU_ITEM_KEYS))
        if unknown:
            raise serializers.ValidationError(f'Unknown menu item key(s): {", ".join(unknown)}.')
        seen = []
        for key in value:
            if key not in seen:
                seen.append(key)
        return seen


class OfficeInboxConfigSerializer(serializers.ModelSerializer):
    """Step 10 — read/update shape for one Office's Inbox configuration.
    Foundation only: saving this never sends a message or drives any
    WhatsApp flow (no webhook/persist_message code reads this model at
    all yet)."""

    class Meta:
        model = OfficeInboxConfig
        fields = ['enabled', 'welcome_message', 'waiting_message', 'offline_message', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class UserSerializer(serializers.ModelSerializer):
    """Read shape for list/detail/create/update responses — one
    serializer for all of them (no extra fields any one of those needs
    beyond the others), same idea as `apps.blast.serializers`'s List/
    Detail split, just with nothing left over to add for Detail here.
    `is_superuser` is read-only/informational only — never settable via
    this serializer or any other in this module; creating or promoting a
    Superadmin stays a Django-only action, out of this API entirely."""

    role = serializers.SerializerMethodField()
    office = serializers.SerializerMethodField()
    initial = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'is_active',
            'is_superuser', 'role', 'office', 'initial', 'date_joined',
        ]
        read_only_fields = fields

    def get_initial(self, obj):
        # `select_related('profile')` in `_users_queryset()` — no per-row
        # query. `''` for a user created before UserProfile existed
        # (never backfilled, this project's own established convention).
        profile = getattr(obj, 'profile', None)
        return profile.initial if profile else ''

    def get_role(self, obj):
        membership = getattr(obj, 'office_membership', None)
        if membership is None:
            return None
        role = membership.role
        return {
            'id': role.id,
            'name': role.name,
            'scopes': role.scopes,
            'grants_global_access': role.grants_global_access,
            'is_office_admin': role.is_office_admin,
            'is_operator': role.is_operator,
        }

    def get_office(self, obj):
        membership = getattr(obj, 'office_membership', None)
        if membership is None or membership.office_id is None:
            return None
        return {'id': membership.office_id, 'name': membership.office.name}


class UserCreateSerializer(serializers.Serializer):
    """POST /api/users/ — creates a Django `User` plus its
    `OfficeMembership` in one call. `context['actor_scope']` is either
    the string `'global'` (Superadmin/Global Admin — any Role/Office) or
    an `Office` instance (an Office Admin's own Office — Role's
    `grants_global_access` must be False, Office forced to that
    instance)."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    # Discussed requirement — set by whoever creates the user, shown to a
    # citizen when this user claims a chat (apps.chats.assignment.claim_chat's
    # own notification, sourced from apps.offices.models.UserProfile).
    # Required (not blank) at creation time — never silently absent for a
    # notification that will need it later.
    initial = serializers.CharField(max_length=10)
    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all())
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), required=False, allow_null=True)

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('username must not be blank.')
        if not USERNAME_PATTERN.match(value):
            raise serializers.ValidationError(USERNAME_RULE_MESSAGE)
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate_initial(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('initial must not be blank.')
        return value

    def validate(self, attrs):
        # Authorization decisions (may this actor assign this role at
        # all?) are the VIEW's job — checked before this serializer even
        # runs, so they surface as 403, not 400 (matching this
        # repository's existing status-code convention: an authorization
        # refusal is 403, a data-shape problem is 400). This only
        # performs the one data TRANSFORMATION with direct Blast
        # precedent: never trust a client-supplied Office for an
        # Office-scoped actor — force their own.
        actor_scope = self.context['actor_scope']
        if actor_scope != 'global':
            attrs['office'] = actor_scope
        _validate_role_office(attrs['role'], attrs.get('office'))
        return attrs

    def create(self, validated_data):
        role = validated_data.pop('role')
        office = validated_data.pop('office', None)
        password = validated_data.pop('password')
        initial = validated_data.pop('initial')
        with transaction.atomic():
            user = User.objects.create_user(password=password, **validated_data)
            OfficeMembership.objects.create(
                user=user, role=role, office=office, requires_office=not role.grants_global_access
            )
            UserProfile.objects.create(user=user, initial=initial)
            _sync_role_groups(user, role)
        return user


class UserProfileUpdateSerializer(serializers.Serializer):
    """PATCH /api/users/<id>/ — profile-only fields, always optional
    (partial update). Role/Office are handled separately by
    `MembershipUpdateSerializer` below, in the same request if the
    caller includes both."""

    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    is_active = serializers.BooleanField(required=False)
    initial = serializers.CharField(max_length=10, required=False, allow_blank=False)


class MembershipUpdateSerializer(serializers.Serializer):
    """The role/Office pair of a PATCH — both fields are required
    together (no partial-pairing inference): a client that wants to
    change one must resend the other's current value too, which is what
    the edit form always has on hand anyway. Actor-scope restrictions
    (an Office Admin may not create a Global Admin or move a user to
    another Office) are enforced in `views.py`, not here — this only
    checks data validity."""

    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all())
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), allow_null=True)

    def validate(self, attrs):
        _validate_role_office(attrs['role'], attrs.get('office'))
        return attrs


class MyProfileUpdateSerializer(serializers.Serializer):
    """PATCH /api/auth/me/profile/ — discussed requirement: every role
    (Superadmin/Global Admin/Office Admin/Operator alike) may edit their
    OWN name, initial and password — always optional (partial), always
    `request.user`'s own row (enforced in `views.py`, never a target
    `pk`), same self-service shape as `OperatorAvailabilitySerializer`.
    Changing the password requires `current_password` (re-authentication,
    not just an active session) — checked in `views.py`, not here."""

    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    initial = serializers.CharField(max_length=10, required=False, allow_blank=False)
    current_password = serializers.CharField(write_only=True, required=False)
    new_password = serializers.CharField(write_only=True, required=False, min_length=8)

    def validate(self, attrs):
        if 'new_password' in attrs and 'current_password' not in attrs:
            raise serializers.ValidationError({'current_password': 'Required to change your password.'})
        return attrs


class OperatorAvailabilitySerializer(serializers.Serializer):
    """PATCH /api/auth/me/availability/ — Step 14. Self-service only; the
    caller's own row, never anyone else's (enforced in views.py, not
    here)."""

    is_available = serializers.BooleanField()
