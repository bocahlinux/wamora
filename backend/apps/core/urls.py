from django.urls import path

from .views import DatabaseHealthView, LivenessView, RedisHealthView

urlpatterns = [
    path('health/', LivenessView.as_view(), name='health-liveness'),
    path('health/database/', DatabaseHealthView.as_view(), name='health-database'),
    path('health/redis/', RedisHealthView.as_view(), name='health-redis'),
]
