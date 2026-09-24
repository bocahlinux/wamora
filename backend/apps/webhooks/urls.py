from django.urls import path

from .views import WahaWebhookView

urlpatterns = [
    path('waha/', WahaWebhookView.as_view(), name='webhook-waha'),
]
