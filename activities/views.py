import logging
from datetime import UTC, date, datetime, time, timedelta


logger = logging.getLogger(__name__)

from rest_framework import status
from rest_framework.exceptions import ValidationError
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
MAX_START_AT_WINDOWS = 93


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


def _parse_filter_date(value, field_name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must use YYYY-MM-DD format')


def _parse_filter_time(value, field_name):
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must use HH:MM format')


def _apply_start_at_window_filters(queryset, *, date_from, date_to, time_from, time_to):
    """
    Applies UTC schedule filters as connected datetime windows.

    The frontend sends date_from/date_to/time_from/time_to already normalized to UTC.
    These values are not independent date/time filters. For each UTC date in the
    range we build a concrete start_at interval and OR the intervals together.
    """
    has_date_filter = bool(date_from or date_to)
    has_time_filter = bool(time_from or time_to)
    if not has_date_filter and not has_time_filter:
        return queryset

    start_date = _parse_filter_date(date_from, 'date_from')
    end_date = _parse_filter_date(date_to, 'date_to')
    start_time = _parse_filter_time(time_from, 'time_from') or time(0, 0)
    end_time = _parse_filter_time(time_to, 'time_to') or time(0, 0)

    if start_date is None and end_date is None:
        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=MAX_START_AT_WINDOWS - 1)
    elif start_date is None:
        start_date = end_date
    elif end_date is None:
        end_date = start_date

    if end_date < start_date:
        raise ValueError('date_to must be greater than or equal to date_from')

    days_count = (end_date - start_date).days + 1
    if days_count > MAX_START_AT_WINDOWS:
        raise ValueError(f'date range must not exceed {MAX_START_AT_WINDOWS} days')

    windows_query = Q()
    for day_offset in range(days_count):
        current_date = start_date + timedelta(days=day_offset)
        window_start = datetime.combine(current_date, start_time, tzinfo=UTC)
        window_end = datetime.combine(current_date, end_time, tzinfo=UTC)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        windows_query |= Q(start_at__gte=window_start, start_at__lt=window_end)

    return queryset.filter(windows_query)


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
    если участников больше нет. Бывший организатор остаётся в активности
    как обычный участник (accepted) — если не хочет, может выйти отдельным
    запросом `DELETE /activities/<id>/participants/me`.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, activity_id):
        from participation.models import Participation

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
        if activity.start_at <= timezone.now():
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Нельзя отказаться от организаторства после начала активности'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        prev_organizer = request.user
        result = transfer_organizership_or_cancel(activity)

        # если передали другому — оставляем бывшего организатора в активности
        # как обычного участника, чтобы он мог продолжить ходить как все
        if result == 'transferred':
            Participation.objects.get_or_create(
                activity=activity,
                user=prev_organizer,
                defaults={'status': Participation.Status.ACCEPTED},
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


def apply_activity_filters(
    queryset,
    request,
    *,
    effective_city_settlement=None,
    effective_city_region=None,
    effective_city_country=None,
):
    """
    Применяет SQL- и in-memory-фильтры к queryset активностей.

    НЕ делает: сортировку, пагинацию, подстановку города пользователя.
    Если вызывающему нужен auto-fill города из user.city — пусть передаст
    через effective_city_*.

    Используется на разных списочных endpoint'ах (`/activities`, `/me/my-activities`)
    , чтобы фильтры применялись консистентно.
    """
    q = request.query_params.get('q')
    category_id = request.query_params.get('category_id')
    subcategory_id = request.query_params.get('subcategory_id')
    format_ = request.query_params.get('format')
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

    # текстовый поиск
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

    if effective_city_settlement:
        queryset = queryset.filter(location_settlement__icontains=effective_city_settlement)
    if effective_city_region:
        queryset = queryset.filter(location_region__icontains=effective_city_region)
    if effective_city_country:
        queryset = queryset.filter(location_country__icontains=effective_city_country)

    try:
        queryset = _apply_start_at_window_filters(
            queryset,
            date_from=date_from,
            date_to=date_to,
            time_from=time_from,
            time_to=time_to,
        )
    except ValueError as error:
        raise ValidationError(
            {'code': 'BAD_REQUEST', 'message': str(error)},
        )

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
        candidates = list(queryset.values('id', 'pref_max_participants'))
        candidate_ids = [c['id'] for c in candidates]
        real_count, _, _, _ = _aggregate_participations(candidate_ids)
        available_ids = [
            c['id'] for c in candidates
            if c['pref_max_participants'] is None
            or real_count.get(c['id'], 0) < c['pref_max_participants']
        ]
        queryset = queryset.filter(id__in=available_ids)

    return queryset


class ActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Activity.objects.filter(status=Activity.Status.ACTIVE)

        # трёхуровневая геолокация: city содержит settlement, region, country
        city = request.query_params.get('city')
        city_settlement = request.query_params.get('city_settlement') or city
        city_region = request.query_params.get('city_region')
        city_country = request.query_params.get('city_country')

        # Если фронт передал ХОТЯ БЫ ОДНО из четырёх городских полей,
        # считаем что он явно задал геолокацию поиска — и НЕ подставляем
        # ничего из профиля пользователя. Иначе ситуация «фронт прислал
        # city_country=Spain, бэк дозаполнил settlement=Москва из профиля»
        # ломает поиск. Если фронт не передал ничего — auto-fill города
        # пользователя как поведение по умолчанию для главного списка.
        explicit_city_filter = any(
            request.query_params.get(param)
            for param in ('city', 'city_settlement', 'city_region', 'city_country')
        )
        if not explicit_city_filter:
            if request.user.city_settlement:
                city_settlement = request.user.city_settlement
            if request.user.city_region:
                city_region = request.user.city_region
            if request.user.city_country:
                city_country = request.user.city_country

        queryset = apply_activity_filters(
            queryset, request,
            effective_city_settlement=city_settlement,
            effective_city_region=city_region,
            effective_city_country=city_country,
        )

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
            ActivityDetailSerializer(activity, context={'request': request}).data,
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

        # только организатор может редактировать, и только пока активность не началась
        if activity.organizer != request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Нет прав для редактирования'}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if activity.status != Activity.Status.ACTIVE:
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Нельзя редактировать отменённую активность'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if activity.start_at <= timezone.now():
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Нельзя редактировать активность после начала'}},
                status=status.HTTP_400_BAD_REQUEST,
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
        if activity.status != Activity.Status.ACTIVE:
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Активность уже отменена'}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if activity.start_at <= timezone.now():
            return Response(
                {'error': {'code': 'INVALID_STATE', 'message': 'Нельзя отменить активность после начала'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
