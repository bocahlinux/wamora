from django.urls import path

from . import views

urlpatterns = [
    path('config/', views.BotConfigView.as_view(), name='bot-config'),
    path('menus/', views.BotMenuListCreateView.as_view(), name='bot-menu-list-create'),
    path('menus/<int:pk>/', views.BotMenuDetailView.as_view(), name='bot-menu-detail'),
    path('menus/<int:menu_pk>/items/', views.BotMenuItemListCreateView.as_view(), name='bot-menu-item-list-create'),
    path('items/<int:pk>/', views.BotMenuItemDetailView.as_view(), name='bot-menu-item-detail'),
    path('triggers/', views.BotTriggerListCreateView.as_view(), name='bot-trigger-list-create'),
    path('triggers/<int:pk>/', views.BotTriggerDetailView.as_view(), name='bot-trigger-detail'),
]
