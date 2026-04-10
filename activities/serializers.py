from rest_framework import serializers
from users.serializers import UserSnippetSerializer
from .models import Activity


class LocationSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    address = serializers.CharField()
    name = serializers.CharField(required=False, allow_null=True)
    settlement = serializers.CharField(required=False, allow_null=True)


class PreferencesSerializer(serializers.Serializer):
    gender = serializers.ChoiceField(
        choices=['male', 'female'], required=False, allow_null=True
    )
    ageFrom = serializers.IntegerField(required=False, allow_null=True)
    ageTo = serializers.IntegerField(required=False, allow_null=True)
    level = serializers.ChoiceField(
        choices=['beginner', 'intermediate', 'advanced'], required=False, allow_null=True
    )
    maxParticipants = serializers.IntegerField(required=False, allow_null=True)


class ActivityListItemSerializer(serializers.ModelSerializer):
    """Лёгкая карточка для ленты — без описания и полных коллекций."""
    id = serializers.CharField()
    organizer = UserSnippetSerializer()
    location = serializers.SerializerMethodField()
    preferences = serializers.SerializerMethodField()
    categoryId = serializers.CharField(source='category_id')
    subcategoryId = serializers.CharField(source='subcategory_id', allow_null=True)
    startAt = serializers.DateTimeField(source='start_at')
    endAt = serializers.DateTimeField(source='end_at')
    requiresApproval = serializers.BooleanField(source='requires_approval')
    photoFileIds = serializers.JSONField(source='photo_file_ids')
    participantsCount = serializers.SerializerMethodField()
    maxParticipants = serializers.SerializerMethodField()
    coverPhotoFileId = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            'id', 'title', 'startAt', 'endAt', 'format', 'status',
            'location', 'categoryId', 'subcategoryId', 'coverPhotoFileId',
            'photoFileIds', 'organizer', 'participantsCount', 'maxParticipants',
            'requiresApproval', 'preferences', 'price',
        ]

    def get_location(self, obj):
        return obj.location

    def get_preferences(self, obj):
        return obj.preferences

    def get_participantsCount(self, obj):
        # будет считаться из participation когда сделаем тот модуль
        return 0

    def get_maxParticipants(self, obj):
        return obj.pref_max_participants

    def get_coverPhotoFileId(self, obj):
        # первое фото как обложка
        return obj.photo_file_ids[0] if obj.photo_file_ids else None


class ActivityDetailSerializer(ActivityListItemSerializer):
    """Полная карточка для экрана события."""
    timeZone = serializers.CharField(source='time_zone')
    participantsPreview = serializers.SerializerMethodField()
    isSaved = serializers.SerializerMethodField()
    participationStatus = serializers.SerializerMethodField()

    class Meta(ActivityListItemSerializer.Meta):
        fields = ActivityListItemSerializer.Meta.fields + [
            'description', 'timeZone', 'participantsPreview',
            'isSaved', 'participationStatus',
        ]

    def get_participantsPreview(self, obj):
        # заполним когда будет participation
        return []

    def get_isSaved(self, obj):
        # заполним когда будет saved activities
        return False

    def get_participationStatus(self, obj):
        # заполним когда будет participation
        return None


class CreateActivitySerializer(serializers.ModelSerializer):
    location = LocationSerializer()
    preferences = PreferencesSerializer(required=False)
    categoryId = serializers.CharField(source='category_id')
    subcategoryId = serializers.CharField(source='subcategory_id', required=False, allow_null=True)
    startAt = serializers.DateTimeField(source='start_at')
    endAt = serializers.DateTimeField(source='end_at')
    timeZone = serializers.CharField(source='time_zone', required=False)
    requiresApproval = serializers.BooleanField(source='requires_approval', required=False)
    photoFileIds = serializers.JSONField(source='photo_file_ids', required=False)

    class Meta:
        model = Activity
        fields = [
            'title', 'description', 'categoryId', 'subcategoryId',
            'format', 'location', 'startAt', 'endAt', 'timeZone',
            'preferences', 'requiresApproval', 'photoFileIds', 'price',
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
            **validated_data
        )

        if preferences_data:
            activity.pref_gender = preferences_data.get('gender')
            activity.pref_age_from = preferences_data.get('ageFrom')
            activity.pref_age_to = preferences_data.get('ageTo')
            activity.pref_level = preferences_data.get('level')
            activity.pref_max_participants = preferences_data.get('maxParticipants')

        activity.save()
        return activity


class UpdateActivitySerializer(serializers.ModelSerializer):
    location = LocationSerializer(required=False)
    preferences = PreferencesSerializer(required=False)
    startAt = serializers.DateTimeField(source='start_at', required=False)
    endAt = serializers.DateTimeField(source='end_at', required=False)
    timeZone = serializers.CharField(source='time_zone', required=False)
    requiresApproval = serializers.BooleanField(source='requires_approval', required=False)
    photoFileIds = serializers.JSONField(source='photo_file_ids', required=False)

    class Meta:
        model = Activity
        fields = [
            'title', 'description', 'format', 'location',
            'startAt', 'endAt', 'timeZone', 'preferences',
            'requiresApproval', 'photoFileIds', 'price', 'status',
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

        if preferences_data:
            instance.pref_gender = preferences_data.get('gender', instance.pref_gender)
            instance.pref_age_from = preferences_data.get('ageFrom', instance.pref_age_from)
            instance.pref_age_to = preferences_data.get('ageTo', instance.pref_age_to)
            instance.pref_level = preferences_data.get('level', instance.pref_level)
            instance.pref_max_participants = preferences_data.get('maxParticipants', instance.pref_max_participants)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
