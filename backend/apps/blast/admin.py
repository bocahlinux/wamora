"""Operational convenience only (design audit Section 10, "OPTIONAL, not
blocking") — read-oriented registration, no custom actions that would
bypass the state-machine/compare-and-set discipline in views.py/tasks.py.
"""

from django.contrib import admin

from .models import BlastCampaign, BlastRecipient


class BlastRecipientInline(admin.TabularInline):
    model = BlastRecipient
    extra = 0
    readonly_fields = ['destination', 'status', 'scheduled_for', 'sent_at', 'failure_reason', 'outbound_operation']
    can_delete = False


@admin.register(BlastCampaign)
class BlastCampaignAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'session', 'status', 'created_by', 'approved_by', 'created_at']
    list_filter = ['status', 'session']
    readonly_fields = [
        'session', 'name', 'message_template', 'status', 'created_by', 'approved_by', 'approved_at',
        'rejected_reason', 'created_at', 'updated_at',
    ]
    inlines = [BlastRecipientInline]

    def has_add_permission(self, request):
        # Creation must go through BlastCampaignListCreateView (recipient
        # cap validation, AuditLog, created_by=request.user) — never the
        # admin site.
        return False
