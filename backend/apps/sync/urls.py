from django.urls import path

from .internal_views import ReconciliationTriggerView

urlpatterns = [
    path('reconciliation/trigger/', ReconciliationTriggerView.as_view(), name='reconciliation-trigger'),
]
