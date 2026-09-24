from django.urls import path

from .views import DatabaseHealthView, LivenessView

urlpatterns = [
    path('health/', LivenessView.as_view(), name='health-liveness'),
    path('health/database/', DatabaseHealthView.as_view(), name='health-database'),
]
