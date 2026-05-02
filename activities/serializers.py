from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Activity


class LocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    address = serializers.CharField()
    name = serializers.CharField(required=False, allow_null=True)
    settlement = serializers.CharField(required=False, allow_null=True)
    region = serializers.CharField(required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True)

class PreferencesSerializer(serializers.Serializer):
    gender = serializers.ChoiceField(
        choices=['male', 'female'], required=False, allow_null=True
    )
    age_from = serializers.IntegerField(required=False, allow_null=True)
    age_to = serializers.IntegerField(required=False, allow_null=True)
    level = serializers.ChoiceField(
        choices=['beginner', 'intermediate', 'advanced'], required=False, allow_null=True
    )
    max_participants = serializers.IntegerField(required=False, allow_null=True)


class ActivityListItemSerializer(serializers.ModelSerializer):
    """Лёгкая карточка для ленты — без описания и полных коллекций."""
    id = serializers.CharField()
    organizer = UserSnippetSerializer()
    location = serializers.SerializerMethodField()
    preferences = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    pending_requests_count = serializers.SerializerMethodField()
    max_participants = serializers.SerializerMethodField()
    cover_photo_file_id = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            'id', 'title', 'start_at', 'end_at', 'format', 'status',
            'location', 'category_id', 'subcategory_id', 'cover_photo_file_id',
            'photo_file_ids', 'organizer', 'participants_count', 'pending_requests_count',
            'max_participants', 'requires_approval', 'preferences', 'price',
        ]

    def get_location(self, obj):
        return obj.location

    def get_preferences(self, obj):
        return obj.preferences

    def get_participants_count(self, obj):
        from participation.models import Participation
        return Participation.objects.filter(
            activity=obj,
            status__in=['accepted', 'attended'],
        ).count()

    def get_pending_requests_count(self, obj):
        from participation.models import Participation
        return Participation.objects.filter(
            activity=obj,
            status='pending',
        ).count()

    def get_max_participants(self, obj):
        return obj.pref_max_participants

    def get_cover_photo_file_id(self, obj):
        return obj.photo_file_ids[0] if obj.photo_file_ids else None

    def get_price(self, obj):
        # возвращаем как число а не строку
        return float(obj.price)


class ActivityDetailSerializer(ActivityListItemSerializer):
    """Полная карточка для экрана события."""
    participants_preview = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    participation_status = serializers.SerializerMethodField()
    is_full = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()
    policy_flags = serializers.SerializerMethodField()

    class Meta(ActivityListItemSerializer.Meta):
        fields = ActivityListItemSerializer.Meta.fields + [
            'description', 'time_zone', 'participants_preview',
            'is_saved', 'participation_status', 'is_full', 'spots_left', 'policy_flags',
        ]

    def get_participants_preview(self, obj):
        from participation.models import Participation
        participations = Participation.objects.filter(
            activity=obj,
            status__in=['accepted', 'attended'],
        ).select_related('user')[:5]
        return UserSnippetSerializer([p.user for p in participations], many=True).data

    def get_is_saved(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        from .models import SavedActivity
        return SavedActivity.objects.filter(
            user=request.user,
            activity=obj,
        ).exists()

    def get_participation_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        from participation.models import Participation
        try:
            p = Participation.objects.get(activity=obj, user=request.user)
            return p.status
        except Participation.DoesNotExist:
            return None

    def get_is_full(self, obj):
        if not obj.pref_max_participants:
            return False
        count = self.get_participants_count(obj)
        return count >= obj.pref_max_participants

    def get_spots_left(self, obj):
        if not obj.pref_max_participants:
            return None
        count = self.get_participants_count(obj)
        return max(0, obj.pref_max_participants - count)

    def get_policy_flags(self, obj):
        """Флаги что пользователь может делать с этой активностью."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return {
                'can_join': False,
                'can_leave': False,
                'can_cancel_request': False,
                'can_manage_requests': False,
                'can_rate': False,
                'can_edit': False,
                'can_cancel_activity': False,
            }

        user = request.user
        is_organizer = obj.organizer_id == user.id
        is_active = obj.status == Activity.Status.ACTIVE

        from participation.models import Participation
        participation_status = None
        try:
            p = Participation.objects.get(activity=obj, user=user)
            participation_status = p.status
        except Participation.DoesNotExist:
            pass

        is_participant = participation_status in ['accepted', 'attended']
        is_pending = participation_status == 'pending'
        is_full = self.get_is_full(obj)
        has_attended = participation_status == 'attended'

        return {
            # вступить можно если активен, не организатор, не участник, не заполнен
            'can_join': is_active and not is_organizer and not is_participant and not is_pending and not is_full,
            # выйти можно если участник и активность ещё активна
            'can_leave': is_active and is_participant and not is_organizer,
            # отменить заявку можно если заявка pending
            'can_cancel_request': is_pending,
            # управлять заявками может только организатор
            'can_manage_requests': is_organizer and is_active,
            # оценить можно если посетил активность
            'can_rate': has_attended and not is_organizer,
            # редактировать может только организатор пока активность активна
            'can_edit': is_organizer and is_active,
            # отменить активность может только организатор
            'can_cancel_activity': is_organizer and is_active,
        }


class CreateActivitySerializer(serializers.ModelSerializer):
    location = LocationSerializer()
    preferences = PreferencesSerializer(required=False)

    class Meta:
        model = Activity
        fields = [
            'title', 'description', 'category_id', 'subcategory_id',
            'format', 'location', 'start_at', 'end_at', 'time_zone',
            'preferences', 'requires_approval', 'photo_file_ids', 'price',
        ]

    def create(self, validated_data):
        location_data = validated_data.pop('location')
        preferences_data = validated_data.pop('preferences', None)
        organizer = self.context['request'].user

        activity = Activity(
            organizer=organizer,
            location_latitude=location_data['latitude'],
            location_longitude=location_data['longitude'],
            location_address=location_data['address'],
            location_name=location_data.get('name'),
            location_settlement=location_data.get('settlement'),
            location_region=location_data.get('region'),
            location_country=location_data.get('country'),
            **validated_data
        )

        if preferences_data:
            activity.pref_gender = preferences_data.get('gender')
            activity.pref_age_from = preferences_data.get('age_from')
            activity.pref_age_to = preferences_data.get('age_to')
            activity.pref_level = preferences_data.get('level')
            activity.pref_max_participants = preferences_data.get('max_participants')

        activity.save()
        return activity


class UpdateActivitySerializer(serializers.ModelSerializer):
    location = LocationSerializer(required=False)
    preferences = PreferencesSerializer(required=False)

    class Meta:
        model = Activity
        fields = [
            'title', 'description', 'format', 'location',
            'start_at', 'end_at', 'time_zone', 'preferences',
            'requires_approval', 'photo_file_ids', 'price', 'status',
        ]
        extra_kwargs = {field: {'required': False} for field in fields}

    def update(self, instance, validated_data):
        location_data = validated_data.pop('location', None)
        preferences_data = validated_data.pop('preferences', None)

        if location_data:
            instance.location_latitude = location_data['latitude']
            instance.location_longitude = location_data['longitude']
            instance.location_address = location_data['address']
            instance.location_name = location_data.get('name')
            instance.location_settlement = location_data.get('settlement')
            instance.location_region = location_data.get('region')
            instance.location_country = location_data.get('country')

        if preferences_data:
            instance.pref_gender = preferences_data.get('gender', instance.pref_gender)
            instance.pref_age_from = preferences_data.get('age_from', instance.pref_age_from)
            instance.pref_age_to = preferences_data.get('age_to', instance.pref_age_to)
            instance.pref_level = preferences_data.get('level', instance.pref_level)
            instance.pref_max_participants = preferences_data.get('max_participants', instance.pref_max_participants)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
