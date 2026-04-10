from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Participation


class ParticipationStatusSerializer(serializers.Serializer):
    """Короткий ответ на действия join/leave/approve/reject."""
    activityId = serializers.SerializerMethodField()
    participationStatus = serializers.CharField(source='status', allow_null=True)

    def get_activityId(self, obj):
        return str(obj.activity_id)


class ActivityParticipantSerializer(serializers.ModelSerializer):
    """Участник в списке участников активности."""
    user = UserSnippetSerializer()
    participationStatus = serializers.CharField(source='status')

    class Meta:
        model = Participation
        fields = ['user', 'participationStatus']