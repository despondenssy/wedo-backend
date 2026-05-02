from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Participation


class ActivityParticipantSerializer(serializers.ModelSerializer):
    """Участник в списке участников активности."""
    user = UserSnippetSerializer()
    participation_status = serializers.CharField(source='status')
    joined_at = serializers.DateTimeField(source='created_at')
    is_organizer = serializers.SerializerMethodField()

    class Meta:
        model = Participation
        fields = ['user', 'participation_status', 'joined_at', 'is_organizer']

    def get_is_organizer(self, obj):
        return obj.activity.organizer_id == obj.user_id


class ActivityJoinRequestSerializer(serializers.ModelSerializer):
    """Заявка на участие — для списка join-requests организатора."""
    user = UserSnippetSerializer()
    request_created_at = serializers.DateTimeField(source='created_at')
    participation_status = serializers.CharField(source='status')

    class Meta:
        model = Participation
        fields = ['user', 'request_created_at', 'participation_status']
