from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import Activity
from .serializers import (
    ActivityListItemSerializer,
    ActivityDetailSerializer,
    CreateActivitySerializer,
    UpdateActivitySerializer,
)


class ActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Activity.objects.filter(status=Activity.Status.ACTIVE)

        # фильтрация
        category_id = request.query_params.get('categoryId')
        subcategory_id = request.query_params.get('subcategoryId')
        format_ = request.query_params.get('format')
        city = request.query_params.get('city')
        date_from = request.query_params.get('dateFrom')
        date_to = request.query_params.get('dateTo')
        level = request.query_params.get('level')
        gender = request.query_params.get('gender')
        age_from = request.query_params.get('ageFrom')
        age_to = request.query_params.get('ageTo')
        requires_approval = request.query_params.get('requiresApproval')
        only_available = request.query_params.get('onlyAvailable')

        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if subcategory_id:
            queryset = queryset.filter(subcategory_id=subcategory_id)
        if format_:
            queryset = queryset.filter(format=format_)
        if city:
            queryset = queryset.filter(location_settlement__icontains=city)
        if date_from:
            queryset = queryset.filter(start_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(start_at__date__lte=date_to)
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

        # простая cursor pagination по id
        cursor = request.query_params.get('cursor')
        limit = min(int(request.query_params.get('limit', 30)), 50)

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset.select_related('organizer')[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': ActivityListItemSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })

    def post(self, request):
        serializer = CreateActivitySerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        activity = serializer.save()
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


class RecommendedActivitiesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        now = timezone.now()

        queryset = Activity.objects.filter(
            status=Activity.Status.ACTIVE,
            start_at__gte=now,
        ).select_related('organizer').prefetch_related('participations')

        cursor = request.query_params.get('cursor')
        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        # берём больше чтобы после scoring отдать нужное количество
        limit = min(int(request.query_params.get('limit', 30)), 50)
        candidates = list(queryset[:limit * 3])

        scored = []
        for activity in candidates:
            score = self._score(activity, user)
            scored.append((score, activity))

        scored.sort(key=lambda x: x[0], reverse=True)
        items = [a for _, a in scored[:limit]]

        has_more = len(candidates) > limit
        next_cursor = str(items[-1].id) if has_more and items else None

        return Response({
            'items': ActivityListItemSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })

    def _score(self, activity, user):
        W_INTERESTS = 0.33
        W_SUBSCRIPTIONS = 0.25
        W_GEO = 0.17
        W_SIMILAR = 0.17
        W_POPULARITY = 0.08

        return (
            W_INTERESTS * self._interests_score(activity, user) +
            W_SUBSCRIPTIONS * self._subscription_score(activity, user) +
            W_GEO * self._geo_score(activity, user) +
            W_SIMILAR * self._similar_users_score(activity, user) +
            W_POPULARITY * self._popularity_score(activity)
        )

    def _interests_score(self, activity, user):
        """1.0 если категория совпадает с интересами пользователя, иначе 0."""
        if not user.interests:
            return 0.0
        return 1.0 if activity.category_id in user.interests else 0.0

    def _subscription_score(self, activity, user):
        """1.0 если пользователь подписан на организатора."""
        from subscriptions.models import Subscription
        return 1.0 if Subscription.objects.filter(
            follower=user,
            target=activity.organizer,
        ).exists() else 0.0

    def _geo_score(self, activity, user):
        """1.0 если город совпадает, 0.5 если нет координат, 0.0 если разные города."""
        if not user.city_settlement or not activity.location_settlement:
            return 0.5
        if user.city_settlement.lower() == activity.location_settlement.lower():
            return 1.0
        # если есть координаты — считаем расстояние
        if user.city_latitude and user.city_longitude:
            return self._distance_score(
                user.city_latitude, user.city_longitude,
                activity.location_latitude, activity.location_longitude,
            )
        return 0.0

    def _distance_score(self, lat1, lon1, lat2, lon2):
        """Чем ближе — тем выше score. До 50км = 1.0, до 200км = 0.5, дальше = 0.0."""
        import math
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        distance_km = R * 2 * math.asin(math.sqrt(a))

        if distance_km <= 50:
            return 1.0
        elif distance_km <= 200:
            return 0.5
        return 0.0

    def _similar_users_score(self, activity, user):
        """
        Похожие пользователи — те у кого пересекаются интересы с текущим.
        Если они участвуют в активности, score растёт.
        """
        from participation.models import Participation
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if not user.interests:
            return 0.0

        # для JSONField используем contains для каждого интереса
        from django.db.models import Q
        query = Q()
        for interest in user.interests:
            query |= Q(interests__contains=[interest])

        similar_user_ids = User.objects.filter(query).exclude(
            id=user.id
        ).values_list('id', flat=True)[:50]

        if not similar_user_ids:
            return 0.0

        participants_count = Participation.objects.filter(
            activity=activity,
            user_id__in=similar_user_ids,
            status__in=['accepted', 'attended'],
        ).count()

        return min(participants_count / 5, 1.0)

    def _popularity_score(self, activity):
        """Популярность по количеству участников относительно максимума."""
        from participation.models import Participation
        count = Participation.objects.filter(
            activity=activity,
            status__in=['accepted', 'attended'],
        ).count()

        max_participants = activity.pref_max_participants or 20
        return min(count / max_participants, 1.0)
