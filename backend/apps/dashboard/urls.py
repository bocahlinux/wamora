from django.urls import path

from .views import ActivityFeedView, MessagesStatsView

urlpatterns = [
    path('messages/', MessagesStatsView.as_view(), name='dashboard-messages'),
    path('activity/', ActivityFeedView.as_view(), name='dashboard-activity'),
]
