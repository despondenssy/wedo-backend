from django.urls import path
from .views import (
    ActivityListView,
    ActivityDetailView,
    ActivityCancelView,
    ActivityDeclineOrganizershipView,
    RecommendedActivitiesView,
    SavedActivitiesView,
    SavedActivityDetailView,
    ActivityBatchCreateView,
)

urlpatterns = [
    path('activities', ActivityListView.as_view()),
    path('activities/recommended', RecommendedActivitiesView.as_view()),
    path('activities/batch', ActivityBatchCreateView.as_view()),
    path('activities/<int:activity_id>', ActivityDetailView.as_view()),
    path('activities/<int:activity_id>/cancel', ActivityCancelView.as_view()),
    path('activities/<int:activity_id>/decline-organizership', ActivityDeclineOrganizershipView.as_view()),
    path('me/saved-activities', SavedActivitiesView.as_view()),
    path('me/saved-activities/<int:activity_id>', SavedActivityDetailView.as_view()),
]
