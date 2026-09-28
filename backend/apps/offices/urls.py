from django.urls import path

from .views import (
    OfficeDetailView,
    OfficeInboxConfigView,
    OfficeListCreateView,
    RoleDetailView,
    RoleListCreateView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path('offices/', OfficeListCreateView.as_view(), name='office-list-create'),
    path('offices/<int:pk>/', OfficeDetailView.as_view(), name='office-detail'),
    path('offices/<int:pk>/inbox-config/', OfficeInboxConfigView.as_view(), name='office-inbox-config'),
    path('users/', UserListCreateView.as_view(), name='user-list-create'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),
    path('roles/', RoleListCreateView.as_view(), name='role-list-create'),
    path('roles/<int:pk>/', RoleDetailView.as_view(), name='role-detail'),
]
