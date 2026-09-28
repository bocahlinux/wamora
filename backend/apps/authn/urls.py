from django.urls import path

from apps.offices.views import OperatorAvailabilityView

from .views import LoginView, MeView

urlpatterns = [
    path('login/', LoginView.as_view(), name='auth-login'),
    path('me/', MeView.as_view(), name='auth-me'),
    # Step 14 (Operator assignment & availability foundation) — the view
    # lives in apps.offices (co-located with OfficeMembership, the model
    # it mutates); the URL lives here so it reads naturally alongside the
    # existing /api/auth/me/ identity endpoint.
    path('me/availability/', OperatorAvailabilityView.as_view(), name='auth-me-availability'),
]
