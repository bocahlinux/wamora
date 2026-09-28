from django.urls import path

from .internal_views import OperatorChatOfficesView, OperatorChatSelectOfficeView

urlpatterns = [
    path('operator-chat/offices/', OperatorChatOfficesView.as_view(), name='operator-chat-offices'),
    path('operator-chat/select-office/', OperatorChatSelectOfficeView.as_view(), name='operator-chat-select-office'),
]
