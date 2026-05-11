import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.utils import timezone

from .models import Activity, SavedActivity
from .serializers import (
    ActivityListItemSerializer,
    ActivityDetailSerializer,
    CreateActivitySerializer,
    UpdateActivitySerializer,
)


# статусы участия, которые считаются "активными"
_ACTIVE_PARTICIPATION_STATUSES = ('pending', 'accepted', 'attended')


def _aggregate_participations(activity_ids):
    """
    Один SQL-запрос вместо N. Считает участников и pending-заявки
    для всех переданных активностей и возвращает удобные словари.

    Используется и сериализатором (через context) для отображения,
    и алгоритмом рекомендаций для вычисления скоров.
    """
    from participation.models import Participation

    rows = Participation.objects.filter(
        activity_id__in=activity_ids,
        status__in=_ACTIVE_PARTICIPATION_STATUSES,
    ).values_list('activity_id', 'user_id', 'status')

    # реальные участники для UI: accepted + attended
    real_count = {aid: 0 for aid in activity_ids}
    # pending-заявки для значка организатору
    pending_count = {aid: 0 for aid in activity_ids}
    # все активные участия — для расчёта популярности
    total_count = {aid: 0 for aid in activity_ids}
    # set участников для расчёта похожести (Jaccard)
    participant_ids = {aid: set() for aid in activity_ids}

    for activity_id, user_id, status in rows:
        total_count[activity_id] += 1
        participant_ids[activity_id].add(user_id)
        if status in ('accepted', 'attended'):
            real_count[activity_id] += 1
        elif status == 'pending':
            pending_count[activity_id] += 1

    return real_count, pending_count, total_count, participant_ids


# Фиксированные offset'ы для дробных таймзон (в минутах).
# Эти IANA-зоны выбраны на фронте как представители offset'ов и не имеют DST.
_FIXED_TZ_OFFSETS_MINUTES = {
    "Pacific/Marquesas": -570,
    "America/St_Johns": -210,
    "Asia/Kabul": 270,
    "Asia/Kolkata": 330,
    "Asia/Kathmandu": 345,
    "Asia/Yangon": 390,
    "Australia/Eucla": 525,
    "Australia/Darwin": 570,
    "Australia/Lord_Howe": 630,
    "Pacific/Chatham": 765,
}


def get_timezone_offset_hours(dt: datetime, tz_name: str) -> float:
    """
    Возвращает UTC-offset в часах для указанной даты и IANA-таймзоны.

    Для дробных таймзон (Pacific/Marquesas и т.д.) использует фиксированную мапу.
    Для целых (Etc/GMT, Europe/Moscow и т.д.) вычисляет через ZoneInfo
    с учётом DST на указанную дату.
    """
    if tz_name in _FIXED_TZ_OFFSETS_MINUTES:
        return _FIXED_TZ_OFFSETS_MINUTES[tz_name] / 60

    try:
        tz = ZoneInfo(tz_name) #делает из IANA объект, который знает offset для каждой конкретной даты
        local_dt = dt.astimezone(tz) #переводит дату из UTC в локальное время
        offset = local_dt.utcoffset() #считаем offset на эту дату
        if offset is None:
            logger.warning("UTC offset is None for %s at %s", tz_name, dt)
            return None
        return offset.total_seconds() / 3600
    except (ZoneInfoNotFoundError, OSError):
        logger.warning("Unknown or invalid timezone: %s", tz_name)
        return None


def _decode_cursor(cursor):
    """Разбирает составной курсор 'value:id' или простой 'id'.

    В случае невалидного курсора (непарсируемый id) возвращает (None, None),
    чтобы вызывающая сторона могла корректно обработать ошибку.
    """
    if not cursor:
        return None, None
    try:
        if ':' in cursor:
            value, obj_id = cursor.split(':', 1)
            return value, int(obj_id)
        return None, int(cursor)
    except (ValueError, TypeError):
        return None, None


def _encode_cursor(obj, sort_field):
    """Кодирует составной курсор 'sort_field_value:id'."""
    value = getattr(obj, sort_field)
    return f'{value}:{obj.id}'


def transfer_organizership_or_cancel(activity):
    """
    Передаёт организаторство активности следующему участнику в порядке записи.
    Если участников нет — отменяет активность и уведомляет оставшихся.

    Используется в двух сценариях:
    - текущий организатор удалил аккаунт (`MeView.delete`)
    - текущий организатор сам отказался от роли (`ActivityDeclineOrganizershipView`)
    """
    from participation.models import Participation
    from notifications.tasks import _create_notification_and_push
    from notifications.models import Notification

    # следующий кандидат — по дате присоединения, accepted-участник
    next_p = (
        Participation.objects
        .filter(activity=activity, status=Participation.Status.ACCEPTED)
        .select_related('user')
        .order_by('created_at')
        .first()
    )

    if next_p:
        new_organizer = next_p.user
        # участник становится организатором — убираем его из участия
        next_p.delete()
        activity.organizer = new_organizer
        activity.save(update_fields=['organizer'])

        _create_notification_and_push(
            user=new_organizer,
            type=Notification.Type.SYSTEM,
            title='Вы стали организатором',
            message=(
                f'Бывший организатор активности «{activity.title}» покинул её. '
                f'Теперь вы организатор. Если не готовы — нажмите «отказаться».'
            ),
            activity=activity,
        )
        return 'transferred'

    # участников нет — отменяем
    activity.status = Activity.Status.CANCELLED
    activity.cancelled_at = timezone.now()
    activity.save(update_fields=['status', 'cancelled_at'])
    # уведомляем всех кто числился на этой активности — включая pending-заявки,
    # чтобы они не висели на отменённой активности без обратной связи
    remaining = (
        Participation.objects
        .filter(
            activity=activity,
            status__in=[
                Participation.Status.ACCEPTED,
                Participation.Status.ATTENDED,
                Participation.Status.PENDING,
            ],
        )
        .select_related('user')
    )
    for p in remaining:
        _create_notification_and_push(
            user=p.user,
            type=Notification.Type.SYSTEM,
            title='Активность отменена',
            message=f'«{activity.title}» отменена — не нашлось нового организатора.',
            activity=activity,
        )
    return 'cancelled'


class ActivityDeclineOrganizershipView(APIView):
    """POST /activities/:id/decline-organizership — отказаться от роли организатора.

    Передаёт активность следующему по очереди участнику, либо отменяет
    если участников больше нет. Текущий организатор после отказа выбывает.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer_id != request.user.id:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Отказаться может только текущий организатор'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if activity.status != Activity.Status.ACTIVE:
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Активность уже отменена или завершена'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer_organizership_or_cancel(activity)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Activity.objects.filter(status=Activity.Status.ACTIVE)

        # фильтрация
        q = request.query_params.get('q')
        category_id = request.query_params.get('category_id')
        subcategory_id = request.query_params.get('subcategory_id')
        format_ = request.query_params.get('format')
        city = request.query_params.get('city')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        time_from = request.query_params.get('time_from')
        time_to = request.query_params.get('time_to')
        level = request.query_params.get('level')
        gender = request.query_params.get('gender')
        age_from = request.query_params.get('age_from')
        age_to = request.query_params.get('age_to')
        requires_approval = request.query_params.get('requires_approval')
        only_available = request.query_params.get('only_available')
        price_to = request.query_params.get('price_to')
        max_participants = request.query_params.get('max_participants')
        timezone_offset_from = request.query_params.get('time_zone_offset_from')
        timezone_offset_to = request.query_params.get('time_zone_offset_to')

        # текстовый поиск — ищем в названии, описании и категориях
        if q:
            q_trimmed = q.strip()
            if q_trimmed:
                queryset = queryset.filter(
                    Q(title__icontains=q_trimmed) |
                    Q(description__icontains=q_trimmed) |
                    Q(category_id__icontains=q_trimmed) |
                    Q(subcategory_id__icontains=q_trimmed)
                )

        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if subcategory_id:
            queryset = queryset.filter(subcategory_id=subcategory_id)
        if format_:
            queryset = queryset.filter(format=format_)

        # трёхуровневая геолокация: city содержит settlement, region, country
        city_settlement = request.query_params.get('city_settlement') or city
        city_region = request.query_params.get('city_region')
        city_country = request.query_params.get('city_country')

        # если фронт не передал город — подставляем город пользователя (как в рекомендациях)
        if not city_settlement and request.user.city_settlement:
            city_settlement = request.user.city_settlement
        if not city_region and request.user.city_region:
            city_region = request.user.city_region
        if not city_country and request.user.city_country:
            city_country = request.user.city_country

        if city_settlement:
            queryset = queryset.filter(location_settlement__icontains=city_settlement)
        if city_region:
            queryset = queryset.filter(location_region__icontains=city_region)
        if city_country:
            queryset = queryset.filter(location_country__icontains=city_country)

        if date_from:
            queryset = queryset.filter(start_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(start_at__date__lte=date_to)
        if time_from:
            queryset = queryset.filter(start_at__time__gte=time_from)
        if time_to:
            queryset = queryset.filter(start_at__time__lte=time_to)
        if level:
            queryset = queryset.filter(pref_level=level)
        if gender:
            queryset = queryset.filter(pref_gender=gender)
        if age_from:
            queryset = queryset.filter(pref_age_from__gte=age_from)
        if age_to:
            queryset = queryset.filter(pref_age_to__lte=age_to)
        if requires_approval is not None:
            queryset = queryset.filter(requires_approval=requires_approval == 'true')
        if price_to:
            queryset = queryset.filter(price__lte=price_to)
        if max_participants:
            queryset = queryset.filter(pref_max_participants__lte=max_participants)

        # only_available: исключаем заполненные активности
        if only_available == 'true':
            # один запрос: id + max_participants для всех кандидатов
            candidates = list(queryset.values('id', 'pref_max_participants'))
            candidate_ids = [c['id'] for c in candidates]
            real_count, _, _, _ = _aggregate_participations(candidate_ids)
            available_ids = [
                c['id'] for c in candidates
                if c['pref_max_participants'] is None
                or real_count.get(c['id'], 0) < c['pref_max_participants']
            ]
            queryset = queryset.filter(id__in=available_ids)

        # --- in-memory фильтр по часовому поясу (только для online) ---
        # Применяется после SQL-фильтров, т.к. offset зависит от start_at и time_zone
        if format_ == 'online' and (timezone_offset_from is not None or timezone_offset_to is not None):
            min_offset = float(timezone_offset_from) if timezone_offset_from else float('-inf')
            max_offset = float(timezone_offset_to) if timezone_offset_to else float('inf')

            # Загружаем id и нужные поля в память для вычисления offset
            all_filtered = list(queryset.values('id', 'start_at', 'time_zone'))
            matching_ids = []
            for item in all_filtered:
                offset = get_timezone_offset_hours(item['start_at'], item['time_zone'])
                if offset is None:
                    continue  # неизвестная таймзона — пропускаем
                if min_offset <= offset <= max_offset:
                    matching_ids.append(item['id'])

            queryset = queryset.filter(id__in=matching_ids)

        # --- сортировка ---
        sort = request.query_params.get('sort', 'created_at')
        order = request.query_params.get('order', 'desc')

        if order == 'asc':
            sort_field = sort
        else:
            sort_field = f'-{sort}'

        queryset = queryset.order_by(sort_field)

        # --- пагинация ---
        cursor = request.query_params.get('cursor')
        limit = min(int(request.query_params.get('limit', 30)), 50)

        # Определяем, используется ли стандартная сортировка (-created_at)
        is_default_sort = (sort == 'created_at' and order == 'desc')

        if cursor:
            cursor_value, cursor_id = _decode_cursor(cursor)
            if cursor_value is None and cursor_id is None:
                return Response(
                    {'detail': 'Invalid cursor format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if is_default_sort:
                queryset = queryset.filter(id__lt=cursor_id)
            else:
                if order == 'asc':
                    queryset = queryset.filter(
                        Q(**{f'{sort}__gt': cursor_value})
                        | (Q(**{f'{sort}__exact': cursor_value}) & Q(id__gt=cursor_id))
                    )
                else:
                    queryset = queryset.filter(
                        Q(**{f'{sort}__lt': cursor_value})
                        | (Q(**{f'{sort}__exact': cursor_value}) & Q(id__lt=cursor_id))
                    )

        # Берём limit + 1 элементов для определения has_more
        queryset = queryset.select_related('organizer')[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        if has_more:
            last = items[-1]
            if is_default_sort:
                next_cursor = str(last.id)
            else:
                next_cursor = _encode_cursor(last, sort)
        else:
            next_cursor = None

        # один батчевый запрос вместо N+1 в сериализаторе
        real_count, pending_count, _, _ = _aggregate_participations([a.id for a in items])

        return Response({
            'items': ActivityListItemSerializer(
                items,
                many=True,
                context={
                    'request': request,
                    'participants_counts': real_count,
                    'pending_counts': pending_count,
                },
            ).data,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })

    def post(self, request):
        serializer = CreateActivitySerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        activity = serializer.save()

        # уведомление подписчикам организатора — в фоне, чтобы не задерживать ответ
        from notifications.tasks import notify_followers_of_new_activity
        notify_followers_of_new_activity.delay(activity.id)

        return Response(
            ActivityDetailSerializer(activity).data,
            status=status.HTTP_201_CREATED,
        )


class ActivityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, activity_id):
        activity = get_object_or_404(
            Activity.objects.select_related('organizer'),
            id=activity_id,
        )
        return Response(ActivityDetailSerializer(activity, context={'request': request}).data)

    def patch(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        # только организатор может редактировать
        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Нет прав для редактирования'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = UpdateActivitySerializer(activity, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        activity = serializer.save()
        return Response(ActivityDetailSerializer(activity, context={'request': request}).data)
    
    def delete(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)
        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Нет прав для удаления'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        activity.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Нет прав для отмены'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        from django.utils import timezone
        activity.status = Activity.Status.CANCELLED
        activity.cancelled_at = timezone.now()
        activity.save()

        return Response(ActivityDetailSerializer(activity, context={'request': request}).data)


class ActivityBatchCreateView(APIView):
    """POST /activities/batch — создать несколько активностей."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        activities_data = request.data.get('activities', [])
        if not activities_data:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'activities обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        for item in activities_data:
            serializer = CreateActivitySerializer(
                data=item, context={'request': request}
            )
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            activity = serializer.save()
            created.append(activity)

        return Response(
            ActivityDetailSerializer(created, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class RecommendedActivitiesView(APIView):
    permission_classes = [IsAuthenticated]

    # веса в формуле итогового скора рекомендаций
    W_INTERESTS = 0.33
    W_SUBSCRIPTIONS = 0.25
    W_GEO = 0.17
    W_SIMILAR = 0.17
    W_POPULARITY = 0.08

    # расстояние, дальше которого вклад от близости уже 0
    D_MAX_KM = 200.0

    def get(self, request):
        from participation.models import Participation
        from subscriptions.models import Subscription
        from django.db.models import Q

        user = request.user
        now = timezone.now()

        queryset = Activity.objects.filter(
            status=Activity.Status.ACTIVE,
            start_at__gte=now,
        ).select_related('organizer')

        # предварительная фильтрация по городу-региону-стране пользователя
        if user.city_settlement:
            queryset = queryset.filter(location_settlement__icontains=user.city_settlement)
        if user.city_region:
            queryset = queryset.filter(location_region__icontains=user.city_region)
        if user.city_country:
            queryset = queryset.filter(location_country__icontains=user.city_country)

        # исключаем события к которым пользователь уже присоединился или организовал
        already_joined = Participation.objects.filter(
            user=user,
            status__in=_ACTIVE_PARTICIPATION_STATUSES,
        ).values_list('activity_id', flat=True)
        queryset = queryset.exclude(id__in=already_joined).exclude(organizer=user)

        cursor = request.query_params.get('cursor')
        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        limit = min(int(request.query_params.get('limit', 30)), 50)
        candidates = list(queryset[:limit * 3])

        if not candidates:
            return Response({'items': [], 'next_cursor': None, 'has_more': False})

        candidate_ids = [a.id for a in candidates]

        # === ОДНОРАЗОВЫЕ БАТЧИ — вместо запросов в цикле ===

        # 1 запрос: считаем сразу всё про участия — реальное число для UI,
        # pending для организатора, total для скоринга, set участников для Jaccard
        real_count, pending_count, total_count, participants_per_activity = (
            _aggregate_participations(candidate_ids)
        )
        n_max = max(total_count.values()) if total_count.values() else 1

        # 1 запрос: id организаторов, на которых подписан пользователь
        followed_organizer_ids = set(
            Subscription.objects.filter(follower=user).values_list('target_id', flat=True)
        )

        # 1 запрос: похожие пользователи (хотя бы один общий интерес)
        similar_users: list = []
        if user.interests:
            interest_query = Q()
            for interest in user.interests:
                interest_query |= Q(interests__contains=[interest])
            User = get_user_model()
            similar_users = list(
                User.objects.filter(interest_query).exclude(id=user.id)[:50]
            )

        # === СКОРИНГ — теперь без обращений к БД ===
        scored = []
        for activity in candidates:
            score = self._score(
                activity,
                user,
                n_max=n_max,
                participants_count=total_count.get(activity.id, 0),
                participant_ids=participants_per_activity.get(activity.id, set()),
                followed_organizer_ids=followed_organizer_ids,
                similar_users=similar_users,
            )
            scored.append((score, activity))

        scored.sort(key=lambda x: x[0], reverse=True)
        items = [a for _, a in scored[:limit]]

        has_more = len(candidates) > limit
        next_cursor = str(items[-1].id) if has_more and items else None

        return Response({
            'items': ActivityListItemSerializer(
                items,
                many=True,
                context={
                    'request': request,
                    'participants_counts': real_count,
                    'pending_counts': pending_count,
                },
            ).data,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })

    def _score(self, activity, user, *, n_max, participants_count,
               participant_ids, followed_organizer_ids, similar_users):
        return (
            self.W_INTERESTS * self._interests_score(activity, user) +
            self.W_SUBSCRIPTIONS * self._subscription_score(activity, followed_organizer_ids) +
            self.W_GEO * self._geo_score(activity, user) +
            self.W_SIMILAR * self._similar_users_score(user, participant_ids, similar_users) +
            self.W_POPULARITY * self._popularity_score(participants_count, n_max)
        )

    def _interests_score(self, activity, user):
        """I(e,u): 1.0 если подкатегория в интересах, 0.5 если только категория, иначе 0."""
        if not user.interests:
            return 0.0
        if activity.subcategory_id and activity.subcategory_id in user.interests:
            return 1.0
        if activity.category_id in user.interests:
            return 0.5
        return 0.0

    def _subscription_score(self, activity, followed_organizer_ids):
        """S(e,u): 1.0 если пользователь подписан на организатора, иначе 0."""
        return 1.0 if activity.organizer_id in followed_organizer_ids else 0.0

    def _geo_score(self, activity, user):
        """
        G(e,u) = max(0, 1 - d(u,e) / d_max).
        Расстояние считается по формуле гаверсинусов. d_max = 200 км.
        """
        if not user.city_latitude or not user.city_longitude:
            return 0.0
        if not activity.location_latitude or not activity.location_longitude:
            return 0.0

        d = self._haversine(
            user.city_latitude, user.city_longitude,
            activity.location_latitude, activity.location_longitude,
        )
        return max(0.0, 1.0 - d / self.D_MAX_KM)

    def _haversine(self, lat1, lon1, lat2, lon2):
        """Формула гаверсинусов для расчёта расстояния по поверхности Земли."""
        import math
        R = 6371
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (math.sin(delta_phi / 2) ** 2 +
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)

        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _similar_users_score(self, user, participant_ids, similar_users):
        """
        B(e,u) = (1/|N_u|) * sum(J(u,v) * y_v_e для v в N_u).
        J(u,v) = |interests_u ∩ interests_v| / |interests_u ∪ interests_v|
        y_v_e = 1 если v участвует в событии e, иначе 0.
        N_u — пользователи с хотя бы одним общим интересом.
        """
        if not user.interests or not similar_users:
            return 0.0

        user_interests = set(user.interests)

        weighted_sum = 0.0
        for v in similar_users:
            if not v.interests:
                continue
            v_interests = set(v.interests)

            # J(u,v) = |A ∩ B| / |A ∪ B|
            intersection = len(user_interests & v_interests)
            union = len(user_interests | v_interests)
            jaccard = intersection / union if union > 0 else 0.0

            # y_v_e = 1 если v участвует, иначе 0
            y_v_e = 1 if v.id in participant_ids else 0

            weighted_sum += jaccard * y_v_e

        return weighted_sum / len(similar_users)

    def _popularity_score(self, participants_count, n_max):
        """
        P(e) = n(e) / n_max.
        n(e) — количество заявок на событие e.
        n_max — максимальное количество заявок среди всех рассматриваемых событий.
        """
        if not n_max:
            return 0.0
        return participants_count / n_max


class SavedActivitiesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """GET /me/saved-activities — список сохранённых активностей."""
        limit = min(int(request.query_params.get('limit', 30)), 50)
        cursor = request.query_params.get('cursor')

        queryset = SavedActivity.objects.filter(
            user=request.user,
        ).select_related('activity', 'activity__organizer').order_by('-saved_at')

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None
        activities = [item.activity for item in items]

        return Response({
            'items': ActivityListItemSerializer(activities, many=True).data,
            'next_cursor': next_cursor,
            'has_more': has_more,
        })


class SavedActivityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        """POST /me/saved-activities/:id — сохранить активность."""
        activity = get_object_or_404(Activity, id=activity_id)

        _, created = SavedActivity.objects.get_or_create(
            user=request.user,
            activity=activity,
        )

        if not created:
            return Response(
                {'error': {'code': 'ALREADY_SAVED', 'message': 'Активность уже сохранена'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request, activity_id):
        """DELETE /me/saved-activities/:id — убрать из сохранённых."""
        saved = get_object_or_404(
            SavedActivity,
            user=request.user,
            activity_id=activity_id,
        )
        saved.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)
