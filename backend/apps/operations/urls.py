from django.urls import path

from .views import OutboundOperationRegisterView, OutboundOperationResolveView

urlpatterns = [
    path('outbound-operations/', OutboundOperationRegisterView.as_view(), name='outbound-operation-register'),
    path('outbound-operations/<int:pk>/', OutboundOperationResolveView.as_view(), name='outbound-operation-resolve'),
]
