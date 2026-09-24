from django.urls import path

from .views import ChatListView, ChatMarkReadView, ChatMessagesView

urlpatterns = [
    path('', ChatListView.as_view(), name='chat-list'),
    path('<int:pk>/messages/', ChatMessagesView.as_view(), name='chat-messages'),
    path('<int:pk>/read/', ChatMarkReadView.as_view(), name='chat-mark-read'),
]
