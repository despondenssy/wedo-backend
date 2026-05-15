from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    type = serializers.CharField()
    timestamp = serializers.DateTimeField(source='created_at')
    read = serializers.SerializerMethodField()
    activity_id = serializers.SerializerMethodField()
    actor_user_id = serializers.SerializerMethodField()
    action_required = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'type', 'title', 'message', 'timestamp',
            'read', 'activity_id', 'actor_user_id', 'action_required',
        ]

    def get_read(self, obj):
        return obj.is_read

    def get_activity_id(self, obj):
        return str(obj.activity_id) if obj.activity_id else None

    def get_actor_user_id(self, obj):
        return str(obj.actor_user_id) if obj.actor_user_id else None

    def get_action_required(self, obj):
        """
        Для actionable-типов проверяем не только сохранённый флаг, но и
        актуальное состояние домена. Если действие уже сделано (заявка
        одобрена/отклонена, оценка оставлена) — флаг становится False,
        и фронт не покажет кнопку.
        """
        if not obj.action_required:
            return False

        from participation.models import Participation
        from ratings.models import ActivityRating

        if obj.type == Notification.Type.JOIN_REQUEST:
            # заявка ещё pending? actor_user — это заявитель
            if obj.activity_id is None or obj.actor_user_id is None:
                return False
            return Participation.objects.filter(
                activity_id=obj.activity_id,
                user_id=obj.actor_user_id,
                status=Participation.Status.PENDING,
            ).exists()

        if obj.type == Notification.Type.RATE_ACTIVITY:
            # пользователь был attended и ещё не оставил оценку
            if obj.activity_id is None:
                return False
            attended = Participation.objects.filter(
                activity_id=obj.activity_id,
                user_id=obj.user_id,
                status=Participation.Status.ATTENDED,
            ).exists()
            already_rated = ActivityRating.objects.filter(
                activity_id=obj.activity_id,
                user_id=obj.user_id,
            ).exists()
            return attended and not already_rated

        if obj.type == Notification.Type.ORGANIZER_ASSIGNED:
            # пользователь всё ещё организатор, активность активна и не началась
            if obj.activity is None:
                return False
            from django.utils import timezone
            from activities.models import Activity
            return (
                obj.activity.organizer_id == obj.user_id
                and obj.activity.status == Activity.Status.ACTIVE
                and obj.activity.start_at > timezone.now()
            )

        return obj.action_required


class UpdateNotificationSerializer(serializers.Serializer):
    read = serializers.BooleanField(required=False)
