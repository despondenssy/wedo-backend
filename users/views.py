import secrets
from datetime import UTC, datetime, timedelta
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model, authenticate
from django.db.models import Q
from django.shortcuts import get_object_or_404
from activities.serializers import ActivityListItemSerializer
from activities.models import Activity
from django.utils import timezone
from .models import QrToken

from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UpdateMeSerializer,
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
        'access_token': str(refresh.access_token),
        'refresh_token': str(refresh),
        'expires_at': unix_timestamp_to_iso8601(refresh.access_token['exp']),
    }


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register'

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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

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

    def delete(self, request):
        from activities.models import Activity
        from activities.views import transfer_organizership_or_cancel

        user = request.user
        now = timezone.now()

        # 1) для каждой будущей активной активности передаём организаторство
        #    следующему участнику. Если участников нет — активность отменяется,
        #    и оставшимся уходит уведомление. Подробности — в хелпере.
        future_activities = list(
            Activity.objects.filter(
                organizer=user,
                status=Activity.Status.ACTIVE,
                start_at__gte=now,
            )
        )
        for activity in future_activities:
            transfer_organizership_or_cancel(activity)

        # 2) анонимизируем персональные данные юзера. Прошлые активности и
        #    оставленные участия не трогаем — у других пользователей сохраняется
        #    история «с кем посещал», а имя удалённого отображается как
        #    «Удалённый аккаунт через UserSnippetSerializer.is_deleted.
        user.deleted_at = now
        user.is_active = False
        user.name = 'Удалённый аккаунт'
        user.email = f'deleted-{user.id}@deleted.local'
        user.avatar_file = None
        user.city_settlement = None
        user.city_region = None
        user.city_country = None
        user.city_latitude = None
        user.city_longitude = None
        user.city_title = None
        user.interests = []
        user.social_link = None
        user.about_me = None
        user.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        serializer = UserProfileSerializer(user, context={'request': request})
        return Response(serializer.data)


class UserHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        return self._handle(request, user_id, apply_filters=False)

    def _handle(self, request, user_id, *, apply_filters):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        tab = request.query_params.get('tab', 'created')
        limit = min(int(request.query_params.get('limit', 20)), 50)
        cursor = request.query_params.get('cursor')

        from participation.models import Participation
        from ratings.models import ActivityRating
        from activities.views import _aggregate_participations

        # «активные» участия для табов participant/all — без rejected и pending
        _PARTICIPATED_STATUSES = (
            Participation.Status.ACCEPTED,
            Participation.Status.ATTENDED,
            Participation.Status.MISSED,
        )

        # для табов organizer/participant/ratings/all отдаём ленту событий
        # (organized/joined/attended/missed/rated/cancelled)
        EVENT_TABS = ('organizer', 'participant', 'ratings', 'all')
        if tab in EVENT_TABS:
            return self._events_response(request, user, tab, limit, cursor, apply_filters=apply_filters)

        if tab == 'created':
            queryset = Activity.objects.filter(
                organizer=user
            ).select_related('organizer')

        elif tab == 'future_created':
            # активности, которые пользователь организует и которые ещё актуальны
            # (используется на экране QR-сканирования организатора)
            queryset = Activity.objects.filter(
                organizer=user,
                status=Activity.Status.ACTIVE,
                end_at__gte=timezone.now(),
            ).select_related('organizer')

        elif tab == 'upcoming':
            # активности где пользователь участник и они ещё не прошли
            activity_ids = Participation.objects.filter(
                user=user,
                status='accepted',
            ).values_list('activity_id', flat=True)
            queryset = Activity.objects.filter(
                id__in=activity_ids,
                end_at__gte=timezone.now(),
                status=Activity.Status.ACTIVE,
            ).select_related('organizer')

        elif tab == 'attended':
            # активности где посещение подтверждено
            activity_ids = Participation.objects.filter(
                user=user,
                status='attended',
            ).values_list('activity_id', flat=True)
            queryset = Activity.objects.filter(
                id__in=activity_ids,
            ).select_related('organizer')

        else:
            return Response(
                {'error': {
                    'code': 'INVALID_TAB',
                    'message': (
                        'Допустимые значения: created, future_created, upcoming, '
                        'attended, organizer, participant, ratings, all'
                    ),
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # фильтры применяются только на /me/my-activities (apply_filters=True).
        if apply_filters:
            from activities.views import apply_activity_filters
            queryset = apply_activity_filters(
                queryset, request,
                effective_city_settlement=request.query_params.get('city_settlement') or request.query_params.get('city'),
                effective_city_region=request.query_params.get('city_region'),
                effective_city_country=request.query_params.get('city_country'),
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
            'next_cursor': next_cursor,
            'has_more': has_more,
        })

    def _events_response(self, request, user, tab, limit, cursor, *, apply_filters):
        """
        Возвращает ленту событий пользователя (organized/cancelled/joined/
        attended/missed/rated). События синтезируются на лету из таблиц
        Activity, Participation и ActivityRating — отдельной таблицы лога нет.

        Курсор — ISO8601 timestamp; берём события строго раньше указанного времени.
        Сортировка по occurred_at desc.

        Фильтры (q, category_id, date_*, format, city_*, и т.д. — те же что
        на /activities) применяются к активностям, из которых синтезируются
        события. Город из профиля юзера тут не подставляется.
        """
        from datetime import datetime
        from participation.models import Participation
        from ratings.models import ActivityRating
        from activities.views import _aggregate_participations, apply_activity_filters

        # 1) собираем сырые "взаимодействия" пользователя с активностями.
        _PARTICIPATED = (
            Participation.Status.ACCEPTED,
            Participation.Status.ATTENDED,
            Participation.Status.MISSED,
        )

        organizer_activity_ids = set()
        participation_by_activity = {}
        rating_by_activity = {}

        if tab in ('organizer', 'all'):
            organizer_activity_ids = set(
                Activity.objects.filter(organizer=user).values_list('id', flat=True)
            )

        if tab in ('participant', 'all'):
            for p in Participation.objects.filter(
                user=user, status__in=_PARTICIPATED,
            ):
                participation_by_activity[p.activity_id] = p

        if tab in ('ratings', 'all'):
            for r in ActivityRating.objects.filter(user=user):
                rating_by_activity[r.activity_id] = r

        relevant_activity_ids = (
            organizer_activity_ids
            | set(participation_by_activity.keys())
            | set(rating_by_activity.keys())
        )

        if not relevant_activity_ids:
            return Response({'items': [], 'next_cursor': None, 'has_more': False})

        # 2) применяем фильтры — только если вызвали через /me/my-activities.
        filtered_qs = Activity.objects.filter(
            id__in=relevant_activity_ids,
        ).select_related('organizer')
        if apply_filters:
            filtered_qs = apply_activity_filters(
                filtered_qs, request,
                effective_city_settlement=request.query_params.get('city_settlement') or request.query_params.get('city'),
                effective_city_region=request.query_params.get('city_region'),
                effective_city_country=request.query_params.get('city_country'),
            )
        activities_by_id = {a.id: a for a in filtered_qs}

        # 3) синтезируем события только из отфильтрованных активностей
        events = []
        for activity_id, activity in activities_by_id.items():
            if activity_id in organizer_activity_ids:
                events.append({
                    'type': 'organized',
                    'occurred_at': activity.created_at,
                    'activity': activity,
                })
                if activity.status == Activity.Status.CANCELLED and activity.cancelled_at:
                    events.append({
                        'type': 'cancelled',
                        'occurred_at': activity.cancelled_at,
                        'activity': activity,
                    })

            if activity_id in participation_by_activity:
                p = participation_by_activity[activity_id]
                events.append({
                    'type': 'joined',
                    'occurred_at': p.created_at,
                    'activity': activity,
                })
                if p.status == Participation.Status.ATTENDED:
                    events.append({
                        'type': 'attended',
                        'occurred_at': p.attendance_marked_at or p.updated_at,
                        'activity': activity,
                    })
                elif p.status == Participation.Status.MISSED:
                    events.append({
                        'type': 'missed',
                        'occurred_at': p.updated_at,
                        'activity': activity,
                    })

            if activity_id in rating_by_activity:
                r = rating_by_activity[activity_id]
                events.append({
                    'type': 'rated',
                    'occurred_at': r.created_at,
                    'activity': activity,
                    'rating': r.rating,
                    'rating_comment': r.comment,
                })

        # сортировка по времени, новые сверху
        events.sort(key=lambda e: e['occurred_at'], reverse=True)

        # курсорная пагинация: events с occurred_at < cursor
        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor.replace('Z', '+00:00'))
                events = [e for e in events if e['occurred_at'] < cursor_dt]
            except ValueError:
                return Response(
                    {'error': {'code': 'INVALID_CURSOR', 'message': 'Курсор должен быть в формате ISO8601'}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # +1 чтобы понять есть ли ещё страница
        page = events[:limit + 1]
        has_more = len(page) > limit
        if has_more:
            page = page[:limit]

        next_cursor = page[-1]['occurred_at'].isoformat() if has_more and page else None

        # батчевый pre-fetch счётчиков для всех активностей на странице
        activity_ids = list({e['activity'].id for e in page})
        real_count, pending_count, _, _ = _aggregate_participations(activity_ids)
        ctx = {
            'request': request,
            'participants_counts': real_count,
            'pending_counts': pending_count,
        }

        items = []
        for e in page:
            item = {
                'type': e['type'],
                'occurred_at': e['occurred_at'].isoformat(),
                'activity': ActivityListItemSerializer(e['activity'], context=ctx).data,
            }
            if e['type'] == 'rated':
                item['rating'] = e['rating']
                item['rating_comment'] = e.get('rating_comment')
            items.append(item)

        return Response({
            'items': items,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })


class QrTokenView(APIView):
    """POST /me/qr-token — получить или обновить свой QR-токен."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'qr_issue'

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
            'expires_at': qr_token.expires_at,
        })


class QrAttendanceScanView(APIView):
    """POST /activities/:id/attendance/scan — отметить посещение через QR."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'qr_scan'

    def post(self, request, activity_id):
        from activities.models import Activity
        from participation.models import Participation
        from django.shortcuts import get_object_or_404

        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer_id != request.user.id: #подгружаем только id юзера
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

        if qr_token.used_at is not None:
            return Response(
                {'error': {'code': 'TOKEN_USED', 'message': 'Токен уже использован'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if qr_token.is_expired:
            return Response(
                {'error': {'code': 'TOKEN_EXPIRED', 'message': 'Токен истёк'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # явные ошибки для трёх сценариев вместо общего 404

        # 1) сканируется сам организатор активности
        if qr_token.user_id == activity.organizer_id:
            return Response(
                {'error': {'code': 'IS_ORGANIZER', 'message': 'Это организатор активности, его отмечать не нужно'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            participation = Participation.objects.get(activity=activity, user=qr_token.user)
        except Participation.DoesNotExist:
            # 2) пользователь вообще не записан на эту активность
            return Response(
                {'error': {'code': 'NOT_PARTICIPANT', 'message': 'Этот пользователь не записан на активность'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3) пользователя уже отсканировали ранее
        if participation.status == Participation.Status.ATTENDED:
            return Response(
                {'error': {'code': 'ALREADY_ATTENDED', 'message': 'Этот пользователь уже отмечен как посетивший'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if participation.status != Participation.Status.ACCEPTED:
            return Response(
                {'error': {
                    'code': 'INVALID_PARTICIPATION_STATE',
                    'message': f'Нельзя отметить участие: текущий статус «{participation.status}»',
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participation.status = Participation.Status.ATTENDED
        participation.attendance_marked_at = timezone.now()
        participation.save()

        # помечаем токен как использованный
        qr_token.used_at = timezone.now()
        qr_token.save()

        # возвращаем имя отсканированного пользователя и новый статус
        from .serializers import UserSnippetSerializer
        return Response({
            'user': UserSnippetSerializer(qr_token.user).data,
            'status': participation.status,
        })


class MyActivitiesView(APIView):
    """GET /me/my-activities — мои активности с поддержкой фильтров.

    Делегирует UserHistoryView, но включает фильтры (q, category_id, format,
    date_*, city_*, и т.д.).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return UserHistoryView()._handle(
            request, user_id=request.user.id, apply_filters=True,
        )


class UserRatingView(APIView):
    """GET /users/:id/rating — рейтинг пользователя."""
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        return Response({'rating': user.rating})


class UserAttendanceHistoryView(APIView):
    """GET /users/:id/attendance-history — история посещений."""
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        from participation.models import Participation
        attended = Participation.objects.filter(user=user, status='attended').count()
        missed = Participation.objects.filter(user=user, status='missed').count()
        return Response({'attended': attended, 'missed': missed})


class LogoutView(APIView):
    """POST /auth/logout — инвалидировать refresh токен."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh_token')
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'

    def post(self, request):
        refresh_token = request.data.get('refresh_token')
        if not refresh_token:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'refresh_token обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            refresh = RefreshToken(refresh_token)
            return Response({
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh),
                'expires_at': unix_timestamp_to_iso8601(refresh.access_token['exp']),
            })
        except Exception:
            return Response(
                {'error': {'code': 'INVALID_TOKEN', 'message': 'Недействительный или истёкший токен'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
