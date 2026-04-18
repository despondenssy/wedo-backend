from django.urls import path
from .views import (
    DeviceTokenView,
    NotificationsListView,
    NotificationDetailView,
    NotificationsReadAllView,
    NotificationsUnreadCountView,
)

urlpatterns = [
    path('me/notifications', NotificationsListView.as_view()),
    path('notifications/read-all', NotificationsReadAllView.as_view()),
    path('notifications/unread-count', NotificationsUnreadCountView.as_view()),
    path('notifications/<int:notification_id>', NotificationDetailView.as_view()),
    path('me/device-token', DeviceTokenView.as_view()),
]