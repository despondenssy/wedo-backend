import secrets
from datetime import UTC, datetime, timedelta
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
from .models import QrToken

from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UpdateMeSerializer,
    UpdatePrivacySerializer,
    UserProfileSerializer,
)

User = get_user_model()


def unix_timestamp_to_iso8601(timestamp):
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def get_tokens(user):
    """Генерирует пару access/refresh токенов для пользователя."""
    refresh = RefreshToken.for_user(user)
    return {
        'accessToken': str(refresh.access_token),
        'refreshToken': str(refresh),
        'expiresAt': unix_timestamp_to_iso8601(refresh.access_token['exp']),
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


class QrTokenView(APIView):
    """POST /me/qr-token — получить или обновить свой QR-токен."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # токен живёт 1 минуту — короткий TTL для безопасности
        expires_at = timezone.now() + timedelta(minutes=1)
        token = f"qr:{request.user.id}:{int(timezone.now().timestamp())}:{secrets.token_hex(4)}"

        # удаляем старые токены пользователя
        QrToken.objects.filter(user=request.user).delete()

        qr_token = QrToken.objects.create(
            user=request.user,
            token=token,
            expires_at=expires_at,
        )

        return Response({
            'token': qr_token.token,
            'expiresAt': qr_token.expires_at,
        })


class QrTokenResolveView(APIView):
    """POST /qr-tokens/resolve — расшифровать QR-токен и получить данные пользователя."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token_str = request.data.get('token')
        if not token_str:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'token обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            qr_token = QrToken.objects.select_related('user').get(token=token_str)
        except QrToken.DoesNotExist:
            return Response(
                {'error': {'code': 'INVALID_TOKEN', 'message': 'Токен не найден или уже использован'}},
                status=status.HTTP_404_NOT_FOUND,
            )

        if qr_token.is_expired:
            return Response(
                {'error': {'code': 'TOKEN_EXPIRED', 'message': 'Токен истёк'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from .serializers import UserSnippetSerializer
        return Response({
            'user': UserSnippetSerializer(qr_token.user).data,
            'expiresAt': qr_token.expires_at,
        })


class QrAttendanceScanView(APIView):
    """POST /activities/:id/attendance/scan — отметить посещение через QR."""
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        from activities.models import Activity
        from participation.models import Participation
        from django.shortcuts import get_object_or_404

        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Только организатор может сканировать QR'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        token_str = request.data.get('token')
        if not token_str:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'token обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            qr_token = QrToken.objects.select_related('user').get(token=token_str)
        except QrToken.DoesNotExist:
            return Response(
                {'error': {'code': 'INVALID_TOKEN', 'message': 'Токен не найден'}},
                status=status.HTTP_404_NOT_FOUND,
            )

        if qr_token.is_expired:
            return Response(
                {'error': {'code': 'TOKEN_EXPIRED', 'message': 'Токен истёк'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participation = get_object_or_404(
            Participation,
            activity=activity,
            user=qr_token.user,
            status=Participation.Status.ACCEPTED,
        )

        participation.status = Participation.Status.ATTENDED
        participation.attendance_marked_at = timezone.now()
        participation.save()

        # помечаем токен как использованный
        qr_token.used_at = timezone.now()
        qr_token.save()

        return Response({
            'activityId': str(activity_id),
            'userId': str(qr_token.user.id),
            'participationStatus': participation.status,
        })


class LogoutView(APIView):
    """POST /auth/logout — инвалидировать refresh токен."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refreshToken')
        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except Exception:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshTokenView(APIView):
    """POST /auth/refresh — получить новый access токен по refresh токену."""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refreshToken')
        if not refresh_token:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'refreshToken обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh = RefreshToken(refresh_token)
            return Response({
                'accessToken': str(refresh.access_token),
                'refreshToken': str(refresh),
                'expiresAt': unix_timestamp_to_iso8601(refresh.access_token['exp']),
            })
        except Exception:
            return Response(
                {'error': {'code': 'INVALID_TOKEN', 'message': 'Недействительный или истёкший токен'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )