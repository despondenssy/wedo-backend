from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from .models import Subscription
from .serializers import (
    SubscriptionSerializer,
    CreateSubscriptionSerializer,
    UpdateSubscriptionSerializer,
)

User = get_user_model()


class SubscriptionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Subscription.objects.filter(
            follower=request.user,
        ).select_related('target')

        pinned_only = request.query_params.get('pinnedOnly')
        if pinned_only == 'true':
            queryset = queryset.filter(is_pinned=True)

        sort = request.query_params.get('sort', 'subscribedAt')
        if sort == 'name':
            queryset = queryset.order_by('target__name')
        else:
            queryset = queryset.order_by('-created_at')

        limit = min(int(request.query_params.get('limit', 30)), 50)
        cursor = request.query_params.get('cursor')

        if cursor:
            queryset = queryset.filter(id__lt=cursor)

        queryset = queryset[:limit + 1]
        items = list(queryset)
        has_more = len(items) > limit
        if has_more:
            items = items[:limit]

        next_cursor = str(items[-1].id) if has_more else None

        return Response({
            'items': SubscriptionSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })

    def post(self, request):
        serializer = CreateSubscriptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        target_id = serializer.validated_data['userId']
        target = get_object_or_404(User, id=target_id)

        if target == request.user:
            return Response(
                {'error': {'code': 'FORBIDDEN', 'message': 'Нельзя подписаться на себя'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription, created = Subscription.objects.get_or_create(
            follower=request.user,
            target=target,
        )

        if not created:
            return Response(
                {'error': {'code': 'ALREADY_SUBSCRIBED', 'message': 'Вы уже подписаны на этого пользователя'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'userId': str(target_id),
            'subscribedAt': subscription.created_at,
            'isPinned': subscription.is_pinned,
        }, status=status.HTTP_201_CREATED)


class SubscriptionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, user_id):
        subscription = get_object_or_404(
            Subscription,
            follower=request.user,
            target_id=user_id,
        )
        subscription.delete()

        return Response({
            'userId': str(user_id),
            'deleted': True,
        })

    def patch(self, request, user_id):
        subscription = get_object_or_404(
            Subscription,
            follower=request.user,
            target_id=user_id,
        )

        serializer = UpdateSubscriptionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if 'isPinned' in serializer.validated_data:
            subscription.is_pinned = serializer.validated_data['isPinned']
            subscription.save()

        return Response({
            'userId': str(user_id),
            'isPinned': subscription.is_pinned,
        })
