from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import UserActivityFeedEvent

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
            'user_id': str(event.user_id),
            'activity_id': str(event.activity_id),
            'type': event.type,
            'occurred_at': event.occurred_at.isoformat(),
            'created_at': event.created_at.isoformat(),
            'actor_user_id': str(event.actor_user_id) if event.actor_user_id else None,
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
            'next_cursor': next_cursor,
            'has_more': has_more,
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
            'next_cursor': next_cursor,
            'has_more': has_more,
        })
