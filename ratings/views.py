from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Avg

from activities.models import Activity
from participation.models import Participation
from .models import ActivityRating
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

        # только посетивший активность может оставить оценку
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

        # пересчитываем рейтинг организатора
        organizer = activity.organizer
        avg = ActivityRating.objects.filter(
            activity__organizer=organizer,
        ).aggregate(avg=Avg('rating'))['avg']
        organizer.rating = round(avg, 2) if avg else 0.0
        organizer.save(update_fields=['rating'])

        return Response(
            ActivityRatingSerializer(rating).data,
            status=status.HTTP_201_CREATED,
        )
