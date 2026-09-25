from django.urls import path

from .views import (
    BlastCampaignApproveView,
    BlastCampaignDetailView,
    BlastCampaignListCreateView,
    BlastCampaignRejectView,
    BlastCampaignSubmitView,
    BlastRecipientResolveView,
)

urlpatterns = [
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
]
