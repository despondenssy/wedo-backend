from django.urls import path
from .views import RegisterView, LoginView, MeView, MePrivacyView, UserDetailView

urlpatterns = [
    path('auth/register', RegisterView.as_view()),
    path('auth/login', LoginView.as_view()),
    path('me', MeView.as_view()),
    path('me/privacy', MePrivacyView.as_view()),
    path('users/<str:user_id>', UserDetailView.as_view()),
]