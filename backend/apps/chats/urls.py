from django.urls import path

from .views import (
    ChatAssignView,
    ChatClaimView,
    ChatCloseSessionView,
    ChatListView,
    ChatMarkReadView,
    ChatMessagesView,
    ChatOperatorsView,
    ChatTransferView,
    ChatUnassignView,
)

urlpatterns = [
    path('', ChatListView.as_view(), name='chat-list'),
    path('<int:pk>/messages/', ChatMessagesView.as_view(), name='chat-messages'),
    path('<int:pk>/read/', ChatMarkReadView.as_view(), name='chat-mark-read'),
    path('<int:pk>/operators/', ChatOperatorsView.as_view(), name='chat-operators'),
    path('<int:pk>/assign/', ChatAssignView.as_view(), name='chat-assign'),
    path('<int:pk>/unassign/', ChatUnassignView.as_view(), name='chat-unassign'),
    path('<int:pk>/claim/', ChatClaimView.as_view(), name='chat-claim'),
    path('<int:pk>/transfer/', ChatTransferView.as_view(), name='chat-transfer'),
    path('<int:pk>/close-session/', ChatCloseSessionView.as_view(), name='chat-close-session'),
]
