from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class CityPlaceSerializer(serializers.Serializer):
    settlement = serializers.CharField()
    region = serializers.CharField()
    country = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    title = serializers.CharField(required=False, allow_blank=True)


class PrivacySerializer(serializers.Serializer):
    showAvatar = serializers.BooleanField()
    showGender = serializers.BooleanField()
    showCityPlace = serializers.BooleanField()
    showInterests = serializers.BooleanField()
    showBirthDate = serializers.BooleanField()
    showAttendanceHistory = serializers.BooleanField()
    showReviews = serializers.BooleanField()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    cityPlace = CityPlaceSerializer()
    showBirthDate = serializers.BooleanField(source='show_birth_date')

    class Meta:
        model = User
        fields = ['name', 'email', 'password', 'birth_date', 'gender', 'cityPlace', 'interests', 'showBirthDate']

    def create(self, validated_data):
        city_data = validated_data.pop('cityPlace')
        password = validated_data.pop('password')

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
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UpdateMeSerializer(serializers.ModelSerializer):
    cityPlace = CityPlaceSerializer(required=False)
    avatarUrl = serializers.URLField(required=False, allow_null=True, source='avatar_url')

    class Meta:
        model = User
        fields = ['name', 'avatarUrl', 'birth_date', 'gender', 'cityPlace', 'interests']
        extra_kwargs = {
            'name': {'required': False},
            'birth_date': {'required': False},
            'gender': {'required': False},
            'interests': {'required': False},
        }

    def update(self, instance, validated_data):
        city_data = validated_data.pop('cityPlace', None)
        if city_data:
            instance.city_settlement = city_data['settlement']
            instance.city_region = city_data['region']
            instance.city_country = city_data['country']
            instance.city_latitude = city_data['latitude']
            instance.city_longitude = city_data['longitude']
            instance.city_title = city_data.get('title', '')

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class UpdatePrivacySerializer(serializers.Serializer):
    showAvatar = serializers.BooleanField(required=False)
    showGender = serializers.BooleanField(required=False)
    showCityPlace = serializers.BooleanField(required=False)
    showInterests = serializers.BooleanField(required=False)
    showBirthDate = serializers.BooleanField(required=False)
    showAttendanceHistory = serializers.BooleanField(required=False)
    showReviews = serializers.BooleanField(required=False)

    def update(self, instance, validated_data):
        mapping = {
            'showAvatar': 'show_avatar',
            'showGender': 'show_gender',
            'showCityPlace': 'show_city_place',
            'showInterests': 'show_interests',
            'showBirthDate': 'show_birth_date',
            'showAttendanceHistory': 'show_attendance_history',
            'showReviews': 'show_reviews',
        }
        for field, db_field in mapping.items():
            if field in validated_data:
                setattr(instance, db_field, validated_data[field])
        instance.save()
        return instance


class UserProfileSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    avatarUrl = serializers.SerializerMethodField()
    cityPlace = serializers.SerializerMethodField()
    privacy = serializers.SerializerMethodField()
    attendanceHistory = serializers.SerializerMethodField()
    isCurrentUser = serializers.SerializerMethodField()
    isSubscribed = serializers.SerializerMethodField()
    reviewsPreview = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    interests = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'avatarUrl', 'rating', 'age', 'gender',
            'cityPlace', 'interests', 'attendanceHistory',
            'reviewsPreview', 'privacy', 'isCurrentUser', 'isSubscribed',
        ]

    def _is_current_user(self, obj):
        override = self.context.get('override_user')
        if override:
            return override.id == obj.id
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return request.user.id == obj.id
        return False

    def get_avatarUrl(self, obj):
        if self._is_current_user(obj) or obj.show_avatar:
            return obj.avatar_url
        return None

    def get_age(self, obj):
        if self._is_current_user(obj) or obj.show_birth_date:
            return obj.age
        return None

    def get_gender(self, obj):
        if self._is_current_user(obj) or obj.show_gender:
            return obj.gender
        return None

    def get_cityPlace(self, obj):
        if self._is_current_user(obj) or obj.show_city_place:
            return obj.city_place
        return None

    def get_interests(self, obj):
        if self._is_current_user(obj) or obj.show_interests:
            return obj.interests
        return None

    def get_privacy(self, obj):
        # privacy видит только сам пользователь
        if self._is_current_user(obj):
            return obj.privacy
        return None

    def get_attendanceHistory(self, obj):
        if self._is_current_user(obj) or obj.show_attendance_history:
            return {'attended': 0, 'missed': 0}
        return None

    def get_isCurrentUser(self, obj):
        return self._is_current_user(obj)

    def get_isSubscribed(self, obj):
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

    def get_reviewsPreview(self, obj):
        if self._is_current_user(obj) or obj.show_reviews:
            return []
        return None

class UserSnippetSerializer(serializers.ModelSerializer):
    """Компактный профиль для вложений — карточки активностей, списки участников."""
    id = serializers.CharField()
    avatarUrl = serializers.URLField(source='avatar_url', allow_null=True)

    class Meta:
        model = User
        fields = ['id', 'name', 'avatarUrl', 'rating']
