from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Avg

from activities.models import Activity
from participation.models import Participation
from .models import ActivityRating
from activities.feed_views import create_feed_event
from .serializers import ActivityRatingSerializer, CreateActivityRatingSerializer


class ActivityRatingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, activity_id):
        get_object_or_404(Activity, id=activity_id)

        limit = min(int(request.query_params.get('limit', 20)), 50)
        cursor = request.query_params.get('cursor')

        queryset = ActivityRating.objects.filter(
            activity_id=activity_id,
        ).select_related('user')

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': ActivityRatingSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })

    def post(self, request, activity_id):
        activity = get_object_or_404(Activity, id=activity_id)

        has_attended = Participation.objects.filter(
            activity=activity,
            user=request.user,
            status=Participation.Status.ATTENDED,
        ).exists()

        if not has_attended:
            return Response(
                {'error': {'code': 'NOT_ATTENDED', 'message': 'Можно оценить только посещённую активность'}},
                status=status.HTTP_403_FORBIDDEN,
            )

        already_rated = ActivityRating.objects.filter(
            activity=activity,
            user=request.user,
        ).exists()

        if already_rated:
            return Response(
                {'error': {'code': 'ALREADY_RATED', 'message': 'Вы уже оценили эту активность'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = CreateActivityRatingSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        rating = serializer.save(activity=activity, user=request.user)

        create_feed_event(request.user, activity, 'rated')

        self._recalculate_organizer_rating(activity.organizer)

        return Response(
            ActivityRatingSerializer(rating).data,
            status=status.HTTP_201_CREATED,
        )

    def _recalculate_organizer_rating(self, organizer):
        """
        R(o) = (v_w * M_w(o) + m * C) / (v_w + m)
        где v_w = sum(lambda(t_i)) — эффективное взвешенное число оценок,
        M_w(o) = sum(lambda(t_i) * r_i) / sum(lambda(t_i)) — взвешенное среднее,
        C — среднее по платформе,
        m — параметр сглаживания.
        """
        import math
        from django.utils import timezone
        from django.contrib.auth import get_user_model

        User = get_user_model()

        # параметры модели
        alpha = 0.01  # скорость затухания: оценка теряет половину веса за ~70 дней
        m = 5         # минимальное доверенное число оценок

        now = timezone.now()

        # все оценки организатора
        ratings = ActivityRating.objects.filter(
            activity__organizer=organizer,
        ).values('rating', 'created_at')

        if not ratings:
            organizer.rating = 0.0
            organizer.save(update_fields=['rating'])
            return

        # считаем взвешенные суммы с учётом временного затухания
        weighted_sum = 0.0
        weight_total = 0.0

        for r in ratings:
            delta_t = (now - r['created_at']).days
            lam = math.exp(-alpha * delta_t)  # λ(t_i) = e^(-α * Δt_i)
            weighted_sum += lam * r['rating']
            weight_total += lam

        # v_w = sum(lambda(t_i))
        v_w = weight_total

        # M_w(o) = sum(lambda * r) / sum(lambda)
        m_w = weighted_sum / weight_total if weight_total > 0 else 0.0

        # C — среднее по платформе (среднее всех рейтингов всех организаторов)
        all_ratings = ActivityRating.objects.all()
        if all_ratings.exists():
            from django.db.models import Avg
            c = all_ratings.aggregate(avg=Avg('rating'))['avg'] or 0.0
        else:
            c = 0.0

        # R(o) = (v_w * M_w(o) + m * C) / (v_w + m)
        r_final = (v_w * m_w + m * c) / (v_w + m)

        organizer.rating = round(r_final, 2)
        organizer.save(update_fields=['rating'])
