from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import Activity, SavedActivity
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
        price_to = request.query_params.get('priceTo')

        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if subcategory_id:
            queryset = queryset.filter(subcategory_id=subcategory_id)
        if format_:
            queryset = queryset.filter(format=format_)

        # трёхуровневая геолокация: city содержит settlement, region, country
        city_settlement = request.query_params.get('citySettlement') or city
        city_region = request.query_params.get('cityRegion')
        city_country = request.query_params.get('cityCountry')

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

        # предварительная фильтрация по городу-региону-стране пользователя
        if user.city_settlement:
            queryset = queryset.filter(
                location_settlement__icontains=user.city_settlement
            )
        if user.city_region:
            queryset = queryset.filter(
                location_region__icontains=user.city_region
            )
        if user.city_country:
            queryset = queryset.filter(
                location_country__icontains=user.city_country
            )

        # исключаем события к которым пользователь уже присоединился или организовал
        from participation.models import Participation
        already_joined = Participation.objects.filter(
            user=user,
            status__in=['pending', 'accepted', 'attended'],
        ).values_list('activity_id', flat=True)
        queryset = queryset.exclude(id__in=already_joined).exclude(organizer=user)

        cursor = request.query_params.get('cursor')
        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        limit = min(int(request.query_params.get('limit', 30)), 50)
        candidates = list(queryset[:limit * 3])

        if not candidates:
            return Response({'items': [], 'nextCursor': None, 'hasMore': False})

        # считаем n_max для формулы P(e) = n(e) / n_max
        from participation.models import Participation
        counts = {
            a.id: Participation.objects.filter(
                activity=a,
                status__in=['pending', 'accepted', 'attended'],
            ).count()
            for a in candidates
        }
        self._n_max = max(counts.values()) if counts else 1

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
        """I(e,u): 1.0 если подкатегория в интересах, 0.5 если только категория, иначе 0."""
        if not user.interests:
            return 0.0
        if activity.subcategory_id and activity.subcategory_id in user.interests:
            return 1.0
        if activity.category_id in user.interests:
            return 0.5
        return 0.0

    def _subscription_score(self, activity, user):
        """S(e,u): 1.0 если пользователь подписан на организатора, иначе 0."""
        from subscriptions.models import Subscription
        return 1.0 if Subscription.objects.filter(
            follower=user,
            target=activity.organizer,
        ).exists() else 0.0

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
        d_max = 200.0
        return max(0.0, 1.0 - d / d_max)

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

    def _similar_users_score(self, activity, user):
        """
        B(e,u) = (1/|N_u|) * sum(J(u,v) * y_v_e для v в N_u).
        J(u,v) = |interests_u ∩ interests_v| / |interests_u ∪ interests_v|
        y_v_e = 1 если v участвует в событии e, иначе 0.
        N_u — пользователи с хотя бы одним общим интересом.
        """
        from participation.models import Participation
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()

        if not user.interests:
            return 0.0

        user_interests = set(user.interests)

        query = Q()
        for interest in user.interests:
            query |= Q(interests__contains=[interest])

        similar_users = list(
            User.objects.filter(query).exclude(id=user.id)[:50]
        )

        if not similar_users:
            return 0.0

        # участники этой активности
        participant_ids = set(
            Participation.objects.filter(
                activity=activity,
                status__in=['pending', 'accepted', 'attended'],
            ).values_list('user_id', flat=True)
        )

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

        n_u = len(similar_users)
        return weighted_sum / n_u

    def _popularity_score(self, activity):
        """
        P(e) = n(e) / n_max.
        n(e) — количество заявок на событие e.
        n_max — максимальное количество заявок среди всех рассматриваемых событий.
        """
        from participation.models import Participation
        count = Participation.objects.filter(
            activity=activity,
            status__in=['pending', 'accepted', 'attended'],
        ).count()

        n_max = getattr(self, '_n_max', None)
        if not n_max:
            return 0.0
        return count / n_max


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
            'nextCursor': next_cursor,
            'hasMore': has_more,
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