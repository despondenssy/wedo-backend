from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    subscribed_at = serializers.DateTimeField(source='created_at')
    user = UserSnippetSerializer(source='target')

    class Meta:
        model = Subscription
        fields = ['user_id', 'subscribed_at', 'is_pinned', 'user']

    def get_user_id(self, obj):
        return str(obj.target_id)


class CreateSubscriptionSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class UpdateSubscriptionSerializer(serializers.Serializer):
    is_pinned = serializers.BooleanField(required=False)
