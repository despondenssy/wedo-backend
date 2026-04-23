from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import Activity, UserActivityFeedEvent

User = get_user_model()

def create_feed_event(user, activity, event_type, actor_user=None, metadata=None):
    """Создать событие в ленте активности."""
    UserActivityFeedEvent.objects.create(
        user=user,
        activity=activity,
        type=event_type,
        occurred_at=timezone.now(),
        actor_user=actor_user,
        metadata=metadata or {},
    )


class UserActivityFeedEventSerializer:
    """Простой сериализатор для событий ленты."""
    @staticmethod
    def serialize(event):
        return {
            'id': str(event.id),
            'userId': str(event.user_id),
            'activityId': str(event.activity_id),
            'type': event.type,
            'occurredAt': event.occurred_at.isoformat(),
            'createdAt': event.created_at.isoformat(),
            'actorUserId': str(event.actor_user_id) if event.actor_user_id else None,
            'metadata': event.metadata,
        }


class MyActivityFeedView(APIView):
    """GET /me/activity-feed — лента активности текущего пользователя."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get('limit', 30)), 50)
        cursor = request.query_params.get('cursor')
        category = request.query_params.get('category')

        queryset = UserActivityFeedEvent.objects.filter(user=request.user)

        if category:
            organizer_types = ['created', 'cancelled']
            participant_types = ['joined', 'leaved', 'attended', 'missed']
            rating_types = ['rated']

            if category == 'organizer':
                queryset = queryset.filter(type__in=organizer_types)
            elif category == 'participant':
                queryset = queryset.filter(type__in=participant_types)
            elif category == 'ratings':
                queryset = queryset.filter(type__in=rating_types)

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': [UserActivityFeedEventSerializer.serialize(e) for e in items],
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })


class UserActivityFeedView(APIView):
    """GET /users/:id/activity-feed — лента активности пользователя."""
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
        limit = min(int(request.query_params.get('limit', 30)), 50)
        cursor = request.query_params.get('cursor')
        category = request.query_params.get('category')

        queryset = UserActivityFeedEvent.objects.filter(user=user)

        if category:
            organizer_types = ['created', 'cancelled']
            participant_types = ['joined', 'leaved', 'attended', 'missed']
            rating_types = ['rated']

            if category == 'organizer':
                queryset = queryset.filter(type__in=organizer_types)
            elif category == 'participant':
                queryset = queryset.filter(type__in=participant_types)
            elif category == 'ratings':
                queryset = queryset.filter(type__in=rating_types)

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': [UserActivityFeedEventSerializer.serialize(e) for e in items],
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })


class ActivityFeedEventCreateView(APIView):
    """POST /activity-feed/events — создать событие вручную."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_id = request.data.get('user_id')
        activity_id = request.data.get('activity_id')
        event_type = request.data.get('type')
        occurred_at = request.data.get('occurred_at')
        actor_user_id = request.data.get('actor_user_id')
        metadata = request.data.get('metadata', {})

        if not all([user_id, activity_id, event_type]):
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'userId, activityId и type обязательны'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        activity = get_object_or_404(Activity, id=activity_id)
        user = get_object_or_404(User, id=user_id)

        event = UserActivityFeedEvent.objects.create(
            user=user,
            activity=activity,
            type=event_type,
            occurred_at=occurred_at or timezone.now(),
            actor_user_id=actor_user_id,
            metadata=metadata or {},
        )

        return Response(
            UserActivityFeedEventSerializer.serialize(event),
            status=status.HTTP_201_CREATED,
        )
