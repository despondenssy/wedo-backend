from django.urls import path
from .views import SubscriptionsListView, SubscriptionDetailView

urlpatterns = [
    path('me/subscriptions', SubscriptionsListView.as_view()),
    path('subscriptions', SubscriptionsListView.as_view()),
    path('subscriptions/<int:user_id>', SubscriptionDetailView.as_view()),
]
