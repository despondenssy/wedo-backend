from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate
from django.shortcuts import get_object_or_404
from activities.serializers import ActivityListItemSerializer
from activities.models import Activity
from django.utils import timezone

from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UpdateMeSerializer,
    UpdatePrivacySerializer,
    UserProfileSerializer,
)

User = get_user_model()


def get_tokens(user):
    """Генерирует пару access/refresh токенов для пользователя."""
    refresh = RefreshToken.for_user(user)
    return {
        'accessToken': str(refresh.access_token),
        'refreshToken': str(refresh),
        'expiresAt': refresh.access_token['exp'],
    }


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        return Response({
            'user': UserProfileSerializer(user, context={'request': request, 'override_user': user}).data,
            'tokens': get_tokens(user),
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(
            request,
            username=serializer.validated_data['email'],
            password=serializer.validated_data['password'],
        )
        if not user:
            return Response(
                {'error': {'code': 'INVALID_CREDENTIALS', 'message': 'Неверный email или пароль'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({
            'user': UserProfileSerializer(user, context={'request': request, 'override_user': user}).data,
            'tokens': get_tokens(user),
        })


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request):
        serializer = UpdateMeSerializer(request.user, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.save()
        return Response(UserProfileSerializer(user, context={'request': request}).data)


class MePrivacyView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = UpdatePrivacySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.update(request.user, serializer.validated_data)
        return Response(request.user.privacy)

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        serializer = UserProfileSerializer(user, context={'request': request})
        return Response(serializer.data)

class UserHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        tab = request.query_params.get('tab', 'created')
        limit = min(int(request.query_params.get('limit', 20)), 50)
        cursor = request.query_params.get('cursor')

        if tab == 'created':
            queryset = Activity.objects.filter(
                organizer=user
            ).select_related('organizer')

        elif tab == 'upcoming':
            # активности где пользователь участник и они ещё не прошли
            from participation.models import Participation
            activity_ids = Participation.objects.filter(
                user=user,
                status='accepted',
            ).values_list('activity_id', flat=True)
            queryset = Activity.objects.filter(
                id__in=activity_ids,
                start_at__gte=timezone.now(),
                status=Activity.Status.ACTIVE,
            ).select_related('organizer')

        elif tab == 'attended':
            # активности где посещение подтверждено
            from participation.models import Participation
            activity_ids = Participation.objects.filter(
                user=user,
                status='attended',
            ).values_list('activity_id', flat=True)
            queryset = Activity.objects.filter(
                id__in=activity_ids,
            ).select_related('organizer')

        else:
            return Response(
                {'error': {'code': 'INVALID_TAB', 'message': 'Допустимые значения: created, upcoming, attended'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset.order_by('-start_at')[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more and items else None

        return Response({
            'items': ActivityListItemSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })
