from django.urls import path
from .views import (
    ActivityListView,
    ActivityDetailView,
    ActivityCancelView,
    RecommendedActivitiesView,
    SavedActivitiesView,
    SavedActivityDetailView,
    ActivityBatchCreateView,
)
from .feed_views import (
    MyActivityFeedView,
    UserActivityFeedView,
    ActivityFeedEventCreateView,
)

urlpatterns = [
    path('activities', ActivityListView.as_view()),
    path('activities/recommended', RecommendedActivitiesView.as_view()),
    path('activities/batch', ActivityBatchCreateView.as_view()),
    path('activities/<int:activity_id>', ActivityDetailView.as_view()),
    path('activities/<int:activity_id>/cancel', ActivityCancelView.as_view()),
    path('me/saved-activities', SavedActivitiesView.as_view()),
    path('me/saved-activities/<int:activity_id>', SavedActivityDetailView.as_view()),
    path('me/activity-feed', MyActivityFeedView.as_view()),
    path('users/<int:user_id>/activity-feed', UserActivityFeedView.as_view()),
    path('activity-feed/events', ActivityFeedEventCreateView.as_view()),
]
