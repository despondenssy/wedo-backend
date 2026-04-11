from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import ActivityRating


class ActivityRatingSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    user = UserSnippetSerializer()
    createdAt = serializers.DateTimeField(source='created_at')

    class Meta:
        model = ActivityRating
        fields = ['id', 'user', 'rating', 'comment', 'createdAt']


class CreateActivityRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityRating
        fields = ['rating', 'comment']

    def validate_rating(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError('Оценка должна быть от 1 до 5')
        return value

    def create(self, validated_data):
        return ActivityRating.objects.create(**validated_data)
