from django.urls import path

from .views import (
    ChatAssignView,
    ChatListView,
    ChatMarkReadView,
    ChatMessagesView,
    ChatOperatorsView,
    ChatUnassignView,
)

urlpatterns = [
    path('', ChatListView.as_view(), name='chat-list'),
    path('<int:pk>/messages/', ChatMessagesView.as_view(), name='chat-messages'),
    path('<int:pk>/read/', ChatMarkReadView.as_view(), name='chat-mark-read'),
    path('<int:pk>/operators/', ChatOperatorsView.as_view(), name='chat-operators'),
    path('<int:pk>/assign/', ChatAssignView.as_view(), name='chat-assign'),
    path('<int:pk>/unassign/', ChatUnassignView.as_view(), name='chat-unassign'),
]
