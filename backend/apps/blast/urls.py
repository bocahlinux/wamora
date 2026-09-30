from django.urls import path

from .views import (
    BlastApiKeyListCreateView,
    BlastApiKeyRevokeView,
    BlastCampaignApproveView,
    BlastCampaignDetailView,
    BlastCampaignListCreateView,
    BlastCampaignRejectView,
    BlastCampaignSubmitView,
    BlastHistoryView,
    BlastOfficeChoicesView,
    BlastRecipientResolveView,
    BlastSettingsView,
    BlastTemplateDetailView,
    BlastTemplateListCreateView,
)

urlpatterns = [
    path('offices/', BlastOfficeChoicesView.as_view(), name='blast-office-choices'),
    path('campaigns/', BlastCampaignListCreateView.as_view(), name='blast-campaign-list-create'),
    path('campaigns/<int:pk>/', BlastCampaignDetailView.as_view(), name='blast-campaign-detail'),
    path('campaigns/<int:pk>/submit/', BlastCampaignSubmitView.as_view(), name='blast-campaign-submit'),
    path('campaigns/<int:pk>/approve/', BlastCampaignApproveView.as_view(), name='blast-campaign-approve'),
    path('campaigns/<int:pk>/reject/', BlastCampaignRejectView.as_view(), name='blast-campaign-reject'),
    path(
        'campaigns/<int:pk>/recipients/<int:recipient_id>/resolve/',
        BlastRecipientResolveView.as_view(),
        name='blast-recipient-resolve',
    ),
    path('templates/', BlastTemplateListCreateView.as_view(), name='blast-template-list-create'),
    path('templates/<int:pk>/', BlastTemplateDetailView.as_view(), name='blast-template-detail'),
    path('api-keys/', BlastApiKeyListCreateView.as_view(), name='blast-api-key-list-create'),
    path('api-keys/<int:pk>/revoke/', BlastApiKeyRevokeView.as_view(), name='blast-api-key-revoke'),
    path('settings/', BlastSettingsView.as_view(), name='blast-settings'),
    path('history/', BlastHistoryView.as_view(), name='blast-history'),
]
