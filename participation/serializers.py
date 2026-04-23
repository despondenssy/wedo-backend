from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Participation


class ActivityParticipantSerializer(serializers.ModelSerializer):
    """Участник в списке участников активности."""
    user = UserSnippetSerializer()
    participationStatus = serializers.CharField(source='status')
    joinedAt = serializers.DateTimeField(source='created_at')
    isOrganizer = serializers.SerializerMethodField()

    class Meta:
        model = Participation
        fields = ['user', 'participationStatus', 'joinedAt', 'isOrganizer']

    def get_isOrganizer(self, obj):
        return obj.activity.organizer_id == obj.user_id


class ActivityJoinRequestSerializer(serializers.ModelSerializer):
    """Заявка на участие — для списка join-requests организатора."""
    user = UserSnippetSerializer()
    requestCreatedAt = serializers.DateTimeField(source='created_at')
    participationStatus = serializers.CharField(source='status')

    class Meta:
        model = Participation
        fields = ['user', 'requestCreatedAt', 'participationStatus']
