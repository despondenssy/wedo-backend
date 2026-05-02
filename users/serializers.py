from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class CitySerializer(serializers.Serializer):
    settlement = serializers.CharField()
    region = serializers.CharField()
    country = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    title = serializers.CharField(required=False, allow_blank=True)


class PrivacySerializer(serializers.Serializer):
    show_avatar = serializers.BooleanField()
    show_gender = serializers.BooleanField()
    show_city = serializers.BooleanField()
    show_interests = serializers.BooleanField()
    show_birth_date = serializers.BooleanField()
    show_attendance_history = serializers.BooleanField()
    show_reviews = serializers.BooleanField()


class PrivacyRegisterSerializer(serializers.Serializer):
    """Privacy настройки при регистрации — все поля опциональны."""
    show_avatar = serializers.BooleanField(required=False, default=True)
    show_gender = serializers.BooleanField(required=False, default=True)
    show_city = serializers.BooleanField(required=False, default=True)
    show_interests = serializers.BooleanField(required=False, default=True)
    show_birth_date = serializers.BooleanField(required=False, default=False)
    show_attendance_history = serializers.BooleanField(required=False, default=True)
    show_reviews = serializers.BooleanField(required=False, default=True)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    city = CitySerializer()
    privacy = PrivacyRegisterSerializer(required=False)

    class Meta:
        model = User
        fields = ['name', 'email', 'password', 'birth_date', 'gender', 'city', 'interests', 'privacy']

    def create(self, validated_data):
        city_data = validated_data.pop('city')
        password = validated_data.pop('password')
        privacy_data = validated_data.pop('privacy', {})

        user = User(
            city_settlement=city_data['settlement'],
            city_region=city_data['region'],
            city_country=city_data['country'],
            city_latitude=city_data['latitude'],
            city_longitude=city_data['longitude'],
            city_title=city_data.get('title', ''),
            **validated_data
        )
        user.set_password(password)

        if privacy_data:
            user.show_avatar = privacy_data.get('show_avatar', True)
            user.show_gender = privacy_data.get('show_gender', True)
            user.show_city = privacy_data.get('show_city', True)
            user.show_interests = privacy_data.get('show_interests', True)
            user.show_birth_date = privacy_data.get('show_birth_date', False)
            user.show_attendance_history = privacy_data.get('show_attendance_history', True)
            user.show_reviews = privacy_data.get('show_reviews', True)

        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UpdateMeSerializer(serializers.ModelSerializer):
    city = CitySerializer(required=False)
    avatar_file_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = User
        fields = ['name', 'avatar_file_id', 'birth_date', 'gender', 'city', 'interests']
        extra_kwargs = {
            'name': {'required': False},
            'birth_date': {'required': False},
            'gender': {'required': False},
            'interests': {'required': False},
        }

    def update(self, instance, validated_data):
        city_data = validated_data.pop('city', None)
        avatar_file_id = validated_data.pop('avatar_file_id', None)

        if city_data:
            instance.city_settlement = city_data['settlement']
            instance.city_region = city_data['region']
            instance.city_country = city_data['country']
            instance.city_latitude = city_data['latitude']
            instance.city_longitude = city_data['longitude']
            instance.city_title = city_data.get('title', '')

        if avatar_file_id is not None:
            from files.models import File
            try:
                instance.avatar_file = File.objects.get(id=avatar_file_id)
            except File.DoesNotExist:
                pass

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class UpdatePrivacySerializer(serializers.Serializer):
    show_avatar = serializers.BooleanField(required=False)
    show_gender = serializers.BooleanField(required=False)
    show_city = serializers.BooleanField(required=False)
    show_interests = serializers.BooleanField(required=False)
    show_birth_date = serializers.BooleanField(required=False)
    show_attendance_history = serializers.BooleanField(required=False)
    show_reviews = serializers.BooleanField(required=False)

    def update(self, instance, validated_data):
        mapping = {
            'show_avatar': 'show_avatar',
            'show_gender': 'show_gender',
            'show_city': 'show_city',
            'show_interests': 'show_interests',
            'show_birth_date': 'show_birth_date',
            'show_attendance_history': 'show_attendance_history',
            'show_reviews': 'show_reviews',
        }
        for field, db_field in mapping.items():
            if field in validated_data:
                setattr(instance, db_field, validated_data[field])
        instance.save()
        return instance


class UserProfileSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    avatar_file_id = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    privacy = serializers.SerializerMethodField()
    attendance_history = serializers.SerializerMethodField()
    is_current_user = serializers.SerializerMethodField()
    is_subscribed = serializers.SerializerMethodField()
    reviews_preview = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    interests = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'avatar_file_id', 'rating', 'age', 'gender',
            'city', 'interests', 'attendance_history',
            'reviews_preview', 'privacy', 'is_current_user', 'is_subscribed',
        ]

    def _is_current_user(self, obj):
        override = self.context.get('override_user')
        if override:
            return override.id == obj.id
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return request.user.id == obj.id
        return False

    def get_avatar_file_id(self, obj):
        if self._is_current_user(obj) or obj.show_avatar:
            return str(obj.avatar_file_id) if obj.avatar_file_id else None
        return None

    def get_age(self, obj):
        if self._is_current_user(obj) or obj.show_birth_date:
            return obj.age
        return None

    def get_gender(self, obj):
        if self._is_current_user(obj) or obj.show_gender:
            return obj.gender
        return None

    def get_city(self, obj):
        if self._is_current_user(obj) or obj.show_city:
            return obj.city
        return None

    def get_interests(self, obj):
        if self._is_current_user(obj) or obj.show_interests:
            return obj.interests
        return None

    def get_privacy(self, obj):
        if self._is_current_user(obj):
            return obj.privacy
        return None

    def get_attendance_history(self, obj):
        if not (self._is_current_user(obj) or obj.show_attendance_history):
            return None
        from participation.models import Participation
        attended = Participation.objects.filter(
            user=obj,
            status='attended',
        ).count()
        missed = Participation.objects.filter(
            user=obj,
            status='missed',
        ).count()
        return {'attended': attended, 'missed': missed}

    def get_is_current_user(self, obj):
        return self._is_current_user(obj)

    def get_is_subscribed(self, obj):
        if self._is_current_user(obj):
            return None
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            from subscriptions.models import Subscription
            return Subscription.objects.filter(
                follower=request.user,
                target=obj,
            ).exists()
        return False

    def get_reviews_preview(self, obj):
        if not (self._is_current_user(obj) or obj.show_reviews):
            return None

        from ratings.models import ActivityRating
        ratings = ActivityRating.objects.filter(
            activity__organizer=obj,
            comment__isnull=False,
        ).select_related('user', 'activity').order_by('-created_at')[:3]

        return [
            {
                'id': str(r.id),
                'from_user_id': str(r.user.id),
                'from_user_name': r.user.name,
                'rating': r.rating,
                'text': r.comment,
                'date': r.created_at.isoformat(),
                'activity_id': str(r.activity.id),
            }
            for r in ratings
        ]


class UserSnippetSerializer(serializers.ModelSerializer):
    """Компактный профиль для вложений — карточки активностей, списки участников."""
    id = serializers.CharField()
    avatar_file_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'avatar_file_id', 'rating']

    def get_avatar_file_id(self, obj):
        return str(obj.avatar_file_id) if obj.avatar_file_id else None
