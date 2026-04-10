from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend

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
        """Рекомендации по интересам и городу текущего пользователя."""
        user = request.user
        queryset = Activity.objects.filter(
            status=Activity.Status.ACTIVE
        ).select_related('organizer')

        if user.interests:
            queryset = queryset.filter(category_id__in=user.interests)

        if user.city_settlement:
            queryset = queryset.filter(location_settlement__icontains=user.city_settlement)

        cursor = request.query_params.get('cursor')
        limit = min(int(request.query_params.get('limit', 30)), 50)

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
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
