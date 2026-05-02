from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    type = serializers.CharField()
    timestamp = serializers.DateTimeField(source='created_at')
    read = serializers.SerializerMethodField()
    activity_id = serializers.SerializerMethodField()
    request_user_id = serializers.SerializerMethodField()
    activity_title = serializers.CharField(allow_null=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'message', 'timestamp',
            'read', 'activity_id', 'request_user_id',
            'action_required', 'activity_title',
        ]

    def get_read(self, obj):
        return obj.is_read

    def get_activity_id(self, obj):
        return str(obj.activity_id) if obj.activity_id else None

    def get_request_user_id(self, obj):
        return str(obj.request_user_id) if obj.request_user_id else None


class UpdateNotificationSerializer(serializers.Serializer):
    read = serializers.BooleanField(required=False)
