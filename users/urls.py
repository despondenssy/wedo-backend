from django.urls import path
from .views import (
    RegisterView, LoginView, MeView, MePrivacyView,
    UserDetailView, UserHistoryView,
    QrTokenView, QrTokenResolveView, QrAttendanceScanView,
    LogoutView, RefreshTokenView,
)

urlpatterns = [
    path('auth/register', RegisterView.as_view()),
    path('auth/login', LoginView.as_view()),
    path('auth/logout', LogoutView.as_view()),
    path('auth/refresh', RefreshTokenView.as_view()),
    path('me', MeView.as_view()),
    path('me/privacy', MePrivacyView.as_view()),
    path('me/qr-token', QrTokenView.as_view()),
    path('users/<int:user_id>', UserDetailView.as_view()),
    path('users/<int:user_id>/history', UserHistoryView.as_view()),
    path('qr-tokens/resolve', QrTokenResolveView.as_view()),
    path('activities/<int:activity_id>/attendance/scan', QrAttendanceScanView.as_view()),
]
