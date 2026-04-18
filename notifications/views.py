from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Notification
from .serializers import NotificationSerializer, UpdateNotificationSerializer


class NotificationsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = Notification.objects.filter(user=request.user)

        unread_only = request.query_params.get('unreadOnly')
        type_ = request.query_params.get('type')

        if unread_only == 'true':
            queryset = queryset.filter(read_at__isnull=True)
        if type_:
            queryset = queryset.filter(type=type_)

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
            'items': NotificationSerializer(items, many=True).data,
            'nextCursor': next_cursor,
            'hasMore': has_more,
        })


class NotificationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user,
        )

        serializer = UpdateNotificationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if serializer.validated_data.get('read') is True:
            notification.read_at = timezone.now()
        elif serializer.validated_data.get('read') is False:
            notification.read_at = None

        notification.save()

        return Response({
            'id': str(notification.id),
            'read': notification.is_read,
        })

    def delete(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user,
        )
        notification.delete()

        return Response({
            'id': str(notification_id),
            'deleted': True,
        })


class NotificationsReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated_count = Notification.objects.filter(
            user=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())

        return Response({
            'success': True,
            'updatedCount': updated_count,
        })


class NotificationsUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = Notification.objects.filter(
            user=request.user,
            read_at__isnull=True,
        ).count()

        return Response({'count': count})


class DeviceTokenView(APIView):
    """POST /me/device-token — сохранить FCM токен устройства."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get('token')
        if not token:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'token обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from notifications.models import DeviceToken
        DeviceToken.objects.update_or_create(
            token=token,
            defaults={'user': request.user},
        )

        return Response(status=status.HTTP_204_NO_CONTENT)
