from django.urls import path

from .external_views import ExternalBlastSendView

urlpatterns = [
    path('blast/send/', ExternalBlastSendView.as_view(), name='blast-external-send'),
]
