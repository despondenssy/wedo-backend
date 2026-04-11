from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    userId = serializers.SerializerMethodField()
    subscribedAt = serializers.DateTimeField(source='created_at')
    isPinned = serializers.BooleanField(source='is_pinned')
    user = UserSnippetSerializer(source='target')

    class Meta:
        model = Subscription
        fields = ['userId', 'subscribedAt', 'isPinned', 'user']

    def get_userId(self, obj):
        return str(obj.target_id)


class CreateSubscriptionSerializer(serializers.Serializer):
    userId = serializers.IntegerField()


class UpdateSubscriptionSerializer(serializers.Serializer):
    isPinned = serializers.BooleanField(required=False)
