from django.conf import settings
from rest_framework import serializers

from apps.offices.authorization import get_user_office, has_global_access
from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession

from .models import BlastCampaign, BlastRecipient, BlastTemplate
from .templating import extract_variable_names


class BlastRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlastRecipient
        fields = ['id', 'destination', 'status', 'scheduled_for', 'sent_at', 'failure_reason', 'variables']
        read_only_fields = fields


class BlastCampaignCreateSerializer(serializers.ModelSerializer):
    """POST /api/blast/campaigns/ — creates a `draft` campaign with its
    recipient list.

    `recipients` accepts a MIXED shape, item by item:
    - a bare string (the original, freeform path — unchanged, additive):
      just a destination, no per-recipient variables.
    - an object `{"destination": str, "variables": {...}}` (the template
      path, used when `template` is given): `variables` must carry
      exactly the set of `{{...}}` names `template.content` declares (via
      `extract_variable_names`) — checked in `validate()` below, where
      ANY single row failing rejects the WHOLE request (400), never a
      partial create.

    `template` is optional; when given, `content` is snapshotted into
    `message_template` server-side — any client-supplied
    `message_template` is ignored in that case (the DB column always
    keeps the literal template text, `{{...}}` placeholders and all, per
    `apps.blast.templating`'s own module docstring)."""

    session = serializers.SlugRelatedField(slug_field='name', queryset=WahaSession.objects.all())
    template = serializers.PrimaryKeyRelatedField(
        queryset=BlastTemplate.objects.filter(is_active=True), required=False, allow_null=True
    )
    # message_template is required only when no template is given — that
    # conditional requirement can't be expressed by the model's own
    # TextField(blank=False), so it's overridden here and enforced in
    # validate() instead of a per-field validate_message_template.
    message_template = serializers.CharField(required=False, allow_blank=True)
    recipients = serializers.ListField(
        child=serializers.JSONField(),
        write_only=True,
        allow_empty=False,
    )
    # Step 4 (Office integration) — required for a globally-accessing
    # creator (superadmin/global admin, who has no Office membership of
    # their own to infer one from); ignored/overwritten for everyone
    # else in `validate()` below, which forces their own Office instead
    # of trusting whatever the client sent — "jangan mempercayai Office
    # arbitrary dari client".
    # Step 6 (Office management) — restricted to active Offices: an
    # inactive Office must not be selectable for a new campaign, matching
    # the same restriction BlastOfficeChoicesView's picker already
    # applies. This is the queryset for an *explicitly client-supplied*
    # office (a globally-accessing creator); the forced-own-office path
    # in `validate()` below has its own explicit is_active check, since
    # it bypasses this field entirely.
    office = serializers.PrimaryKeyRelatedField(
        queryset=Office.objects.filter(is_active=True), required=False, allow_null=True
    )

    class Meta:
        model = BlastCampaign
        fields = [
            'id', 'session', 'office', 'name', 'template', 'message_template', 'recipients', 'status', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('name must not be blank.')
        return value

    def validate_recipients(self, value):
        # Normalizes both accepted shapes (bare string, or
        # {"destination", "variables"}) into one internal shape so every
        # downstream step (dedup, the template-variables check in
        # validate(), create()) has exactly one thing to deal with.
        normalized = []
        for item in value:
            if isinstance(item, str):
                destination = item.strip()
                variables = {}
            elif isinstance(item, dict):
                destination = str(item.get('destination', '')).strip()
                variables = item.get('variables') or {}
                if not isinstance(variables, dict):
                    raise serializers.ValidationError('Each recipient\'s variables must be an object.')
            else:
                raise serializers.ValidationError('Each recipient must be a string or an object.')
            if not destination:
                continue
            normalized.append({'destination': destination, 'variables': variables})
        # Order-preserving de-duplication by destination — the DB-level
        # UniqueConstraint (models.py) is the real enforcement boundary;
        # this just avoids a noisy IntegrityError for the common "pasted
        # list has an accidental repeat" case.
        deduped = list({r['destination']: r for r in normalized}.values())
        if not deduped:
            raise serializers.ValidationError('At least one recipient is required.')
        # Finalized decision 3: max 100 recipients/campaign, enforced at
        # creation.
        max_recipients = settings.BLAST_MAX_RECIPIENTS_PER_CAMPAIGN
        if len(deduped) > max_recipients:
            raise serializers.ValidationError(f'A campaign may have at most {max_recipients} recipients.')
        return deduped

    def validate(self, attrs):
        # Step 4 (Office integration). Runs after every per-field
        # validate_* above, so `attrs['office']` here is either a real
        # Office (client sent one and it exists) or absent/None.
        user = self.context['request'].user
        if has_global_access(user):
            if attrs.get('office') is None:
                raise serializers.ValidationError({'office': 'An Office must be specified.'})
        else:
            user_office = get_user_office(user)
            if user_office is None:
                raise serializers.ValidationError(
                    'You are not assigned to any Office; contact an administrator before creating a campaign.'
                )
            # Force the creator's own Office — never trust a
            # client-supplied one for a non-globally-accessing user.
            attrs['office'] = user_office
        # Step 6 — an inactive Office (retired, per Office management's
        # is_active toggle) must not be usable for a NEW campaign, on
        # either path above (this check runs regardless of whether the
        # Office came from the client-supplied field or the forced-own-
        # Office branch, which bypasses that field's queryset filter).
        if not attrs['office'].is_active:
            raise serializers.ValidationError({'office': 'This Office is not active.'})

        template = attrs.get('template')
        recipients = attrs.get('recipients') or []
        if template is not None:
            # Template path — content is ALWAYS the server-side snapshot,
            # any client-supplied message_template is ignored outright.
            attrs['message_template'] = template.content
            required_vars = extract_variable_names(template.content)
            details = []
            for index, recipient in enumerate(recipients):
                row_vars = recipient['variables']
                row_keys = {key for key, val in row_vars.items() if str(val).strip() != ''}
                missing = required_vars - row_keys
                extra = row_keys - required_vars
                if missing or extra:
                    details.append({
                        'index': index,
                        'destination': recipient['destination'],
                        'missing': sorted(missing),
                        'extra': sorted(extra),
                    })
            if details:
                raise serializers.ValidationError({
                    'recipients': 'One or more recipients have missing or unexpected variables.',
                    'details': details,
                })
        else:
            # Freeform path — message_template is required exactly as
            # before, now enforced here rather than a per-field validator
            # (that field is conditionally required depending on
            # `template`, which a field-level validator can't see).
            message_template = (attrs.get('message_template') or '').strip()
            if not message_template:
                raise serializers.ValidationError({'message_template': 'message_template must not be blank.'})
            attrs['message_template'] = message_template
        return attrs

    def create(self, validated_data):
        recipients = validated_data.pop('recipients')
        request = self.context['request']
        campaign = BlastCampaign.objects.create(created_by=request.user, **validated_data)
        BlastRecipient.objects.bulk_create([
            BlastRecipient(campaign=campaign, destination=r['destination'], variables=r['variables'])
            for r in recipients
        ])
        return campaign


class BlastCampaignListSerializer(serializers.ModelSerializer):
    session = serializers.CharField(source='session.name', read_only=True)
    # Step 4 (Office integration) — None for a legacy/office-less
    # campaign (see BlastCampaign.office's own comment), never omitted.
    office = serializers.SerializerMethodField()
    created_by = serializers.CharField(source='created_by.username', read_only=True)
    approved_by = serializers.CharField(source='approved_by.username', read_only=True, default=None)
    recipient_count = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    source = serializers.SerializerMethodField()

    class Meta:
        model = BlastCampaign
        fields = [
            'id', 'session', 'office', 'name', 'status', 'recipient_count', 'template', 'source',
            'created_by', 'approved_by', 'approved_at', 'created_at', 'updated_at',
        ]

    def get_template(self, obj):
        if obj.template_id is None:
            return None
        return {'id': obj.template_id, 'key': obj.template.key, 'name': obj.template.name}

    def get_source(self, obj):
        return 'api' if obj.triggered_by_api_key_id is not None else 'dashboard'

    def get_office(self, obj):
        if obj.office_id is None:
            return None
        return {'id': obj.office_id, 'name': obj.office.name}

    def get_recipient_count(self, obj):
        return obj.recipients.count()


class BlastTemplateSerializer(serializers.ModelSerializer):
    """CRUD for BlastTemplate — Blast > Templates tab. `variable_names`
    is derived (never stored) via `extract_variable_names`, so the
    frontend's "detected variables" preview always matches exactly what
    server-side campaign/external-API validation will check against."""

    variable_names = serializers.SerializerMethodField()
    created_by = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = BlastTemplate
        fields = [
            'id', 'key', 'name', 'content', 'variable_names', 'office', 'is_active', 'created_by',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_variable_names(self, obj):
        return sorted(extract_variable_names(obj.content))

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError('content must not be blank.')
        return value


class BlastCampaignDetailSerializer(BlastCampaignListSerializer):
    recipients = BlastRecipientSerializer(many=True, read_only=True)

    class Meta(BlastCampaignListSerializer.Meta):
        fields = BlastCampaignListSerializer.Meta.fields + ['message_template', 'rejected_reason', 'recipients']


class OfficeChoiceSerializer(serializers.ModelSerializer):
    """GET /api/blast/offices/ — Step 4's minimal read-only office list,
    for a globally-accessing creator's campaign-create Office picker
    only. Not Office management (no create/edit/deactivate anywhere) —
    explicitly out of this step's scope."""

    class Meta:
        model = Office
        fields = ['id', 'name']


class BlastCampaignRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, required=False, allow_blank=True, default='')


class BlastRecipientResolveSerializer(serializers.Serializer):
    """POST .../recipients/<id>/resolve/ — Phase 11 stuck-recovery fix
    (docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md Section 4).
    Only the two TERMINAL statuses a human operator can honestly attest
    to from outside this system (they checked the real WhatsApp chat) are
    accepted — never `pending`/`sending`/`skipped`, which would either
    re-open dispatch or invent an outcome nobody observed."""

    status = serializers.ChoiceField(choices=[BlastRecipient.STATUS_SENT, BlastRecipient.STATUS_FAILED])
