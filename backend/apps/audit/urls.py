from django.urls import path

from .views import AuditEventCreateView

urlpatterns = [
    path('audit-events/', AuditEventCreateView.as_view(), name='audit-event-create'),
]
