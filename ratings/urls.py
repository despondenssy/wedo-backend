from django.urls import path
from .views import ActivityRatingsView

urlpatterns = [
    path('activities/<int:activity_id>/ratings', ActivityRatingsView.as_view()),
]