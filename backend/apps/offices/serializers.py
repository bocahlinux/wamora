"""Office & User management — Step 6. Plain serializers over the existing
`Office`/`OfficeMembership` models and the stock
`django.contrib.auth.models.User` — no custom User model, no Role/
Permission model (per Step 6's own constraints).

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

from django.contrib.auth.models import Group, User
from django.db import transaction
from rest_framework import serializers

from .models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, Office, OfficeInboxConfig, OfficeMembership

# The 'user administration' JWT scope has been declared in
# settings.JWT_SCOPES since early phases but never checked/granted by
# anything until this step. A superuser gets every scope automatically
# (compute_scopes()'s existing superuser bypass); a non-superuser
# Global/Office Admin needs this Group to get it. Kept in sync here as a
# side effect of setting/clearing an admin role, so a Global/Office Admin
# created through this app's own API can use it immediately on their next
# login — no separate manual `Group`-assignment command required. This
# does not change `compute_scopes()`/JWT issuance itself, and does not use
# Group to represent Office — it only completes the wiring of an
# already-declared, already-designed-for scope.
ADMIN_SCOPE_GROUP_NAME = 'user administration'

# Step 8 (Role x Scope alignment) — 'blast' is the ONE additional Group
# safe to sync directly from role: unlike 'reading' (also gates Dashboard/
# Sessions-status) or 'system administration' (also gates Sync Recovery),
# 'blast' is used ONLY by Blast list/create/detail/submit
# (apps/blast/views.py) — no other feature reads it, so granting it to
# Global/Office Admin carries no cross-domain leak. Blast APPROVE/REJECT
# and Inbox read access are deliberately NOT granted via a Group here at
# all — they go through `apps.authn.permissions.HasOfficeAdminAccess`/
# `HasOfficeAccess` instead (role-checked directly, live, every request),
# specifically so this function never needs to touch 'system
# administration'/'reading' and never risks leaking Sync Recovery/
# Dashboard/Sessions access as a side effect. Operator gets neither Group
# (no Blast creation for Operator in Step 8, per explicit decision).
ROLE_GROUPS = {
    ROLE_GLOBAL_ADMIN: (ADMIN_SCOPE_GROUP_NAME, 'blast'),
    ROLE_OFFICE_ADMIN: (ADMIN_SCOPE_GROUP_NAME, 'blast'),
}

# Every Group name this function ever assigns — also the exact set it
# will remove if a role no longer warrants them (e.g. demoted to
# Operator), so a role change never leaves a stale Group behind.
_MANAGED_GROUP_NAMES = {ADMIN_SCOPE_GROUP_NAME, 'blast'}


def _sync_admin_scope_group(user, role):
    wanted = set(ROLE_GROUPS.get(role, ()))
    for name in _MANAGED_GROUP_NAMES:
        group, _ = Group.objects.get_or_create(name=name)
        if name in wanted:
            user.groups.add(group)
        else:
            user.groups.remove(group)


def _validate_role_office(role, office):
    """Mirrors `OfficeMembership`'s own `office_matches_role`
    CheckConstraint — checked here so a bad combination surfaces as a
    normal 400, not a raw IntegrityError."""
    if role == ROLE_GLOBAL_ADMIN and office is not None:
        raise serializers.ValidationError({'office': 'A Global Admin must not have an Office.'})
    if role != ROLE_GLOBAL_ADMIN and office is None:
        raise serializers.ValidationError({'office': 'This role requires an Office.'})


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

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'is_active',
            'is_superuser', 'role', 'office', 'date_joined',
        ]
        read_only_fields = fields

    def get_role(self, obj):
        membership = getattr(obj, 'office_membership', None)
        return membership.role if membership else None

    def get_office(self, obj):
        membership = getattr(obj, 'office_membership', None)
        if membership is None or membership.office_id is None:
            return None
        return {'id': membership.office_id, 'name': membership.office.name}


class UserCreateSerializer(serializers.Serializer):
    """POST /api/users/ — creates a Django `User` plus its
    `OfficeMembership` in one call. `context['actor_scope']` is either
    the string `'global'` (Superadmin/Global Admin — any role/Office) or
    an `Office` instance (an Office Admin's own Office — role restricted
    to office_admin/operator, Office forced to that instance)."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    role = serializers.ChoiceField(choices=OfficeMembership.ROLE_CHOICES)
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), required=False, allow_null=True)

    def validate_username(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('username must not be blank.')
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
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
        with transaction.atomic():
            user = User.objects.create_user(password=password, **validated_data)
            OfficeMembership.objects.create(user=user, role=role, office=office)
            _sync_admin_scope_group(user, role)
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


class MembershipUpdateSerializer(serializers.Serializer):
    """The role/Office pair of a PATCH — both fields are required
    together (no partial-pairing inference): a client that wants to
    change one must resend the other's current value too, which is what
    the edit form always has on hand anyway. Actor-scope restrictions
    (an Office Admin may not create a Global Admin or move a user to
    another Office) are enforced in `views.py`, not here — this only
    checks data validity."""

    role = serializers.ChoiceField(choices=OfficeMembership.ROLE_CHOICES)
    office = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), allow_null=True)

    def validate(self, attrs):
        _validate_role_office(attrs['role'], attrs.get('office'))
        return attrs


class OperatorAvailabilitySerializer(serializers.Serializer):
    """PATCH /api/auth/me/availability/ — Step 14. Self-service only; the
    caller's own row, never anyone else's (enforced in views.py, not
    here)."""

    is_available = serializers.BooleanField()
