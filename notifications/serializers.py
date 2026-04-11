from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    type = serializers.CharField()
    timestamp = serializers.DateTimeField(source='created_at')
    read = serializers.SerializerMethodField()
    activityId = serializers.SerializerMethodField()
    requestUserId = serializers.SerializerMethodField()
    actionRequired = serializers.BooleanField(source='action_required')
    activityTitle = serializers.CharField(source='activity_title', allow_null=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'message', 'timestamp',
            'read', 'activityId', 'requestUserId',
            'actionRequired', 'activityTitle',
        ]

    def get_read(self, obj):
        return obj.is_read

    def get_activityId(self, obj):
        return str(obj.activity_id) if obj.activity_id else None

    def get_requestUserId(self, obj):
        return str(obj.request_user_id) if obj.request_user_id else None


class UpdateNotificationSerializer(serializers.Serializer):
    read = serializers.BooleanField(required=False)
