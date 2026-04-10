from django.urls import path
from .views import (
    ActivityListView,
    ActivityDetailView,
    ActivityCancelView,
    RecommendedActivitiesView,
)

urlpatterns = [
    path('activities', ActivityListView.as_view()),
    path('activities/recommended', RecommendedActivitiesView.as_view()),
    path('activities/<int:activity_id>', ActivityDetailView.as_view()),
    path('activities/<int:activity_id>/cancel', ActivityCancelView.as_view()),
]
