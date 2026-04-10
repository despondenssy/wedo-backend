from django.urls import path
from .views import (
    ActivityJoinView,
    ActivityJoinRequestView,
    ActivityJoinRequestCancelView,
    ActivityJoinRequestApproveView,
    ActivityJoinRequestRejectView,
    ActivityLeaveView,
    ActivityParticipantsView,
    ActivityJoinRequestsView,
    ActivityAttendanceView,
)

urlpatterns = [
    path('activities/<int:activity_id>/join', ActivityJoinView.as_view()),
    path('activities/<int:activity_id>/join-requests', ActivityJoinRequestView.as_view()),
    path('activities/<int:activity_id>/join-requests/me', ActivityJoinRequestCancelView.as_view()),
    path('activities/<int:activity_id>/join-requests/<int:user_id>/approve', ActivityJoinRequestApproveView.as_view()),
    path('activities/<int:activity_id>/join-requests/<int:user_id>/reject', ActivityJoinRequestRejectView.as_view()),
    path('activities/<int:activity_id>/participants', ActivityParticipantsView.as_view()),
    path('activities/<int:activity_id>/participants/me', ActivityLeaveView.as_view()),
    path('activities/<int:activity_id>/attendance', ActivityAttendanceView.as_view()),
]
