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
    showAvatar = serializers.BooleanField()
    showGender = serializers.BooleanField()
    showCity = serializers.BooleanField()
    showInterests = serializers.BooleanField()
    showBirthDate = serializers.BooleanField()
    showAttendanceHistory = serializers.BooleanField()
    showReviews = serializers.BooleanField()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    city = CitySerializer()
    showBirthDate = serializers.BooleanField(source='show_birth_date')

    class Meta:
        model = User
        fields = ['name', 'email', 'password', 'birth_date', 'gender', 'city', 'interests', 'showBirthDate']

    def create(self, validated_data):
        city_data = validated_data.pop('city')
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
    city = CitySerializer(required=False)
    avatarFileId = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = User
        fields = ['name', 'avatarFileId', 'birth_date', 'gender', 'city', 'interests']
        extra_kwargs = {
            'name': {'required': False},
            'birth_date': {'required': False},
            'gender': {'required': False},
            'interests': {'required': False},
        }

    def update(self, instance, validated_data):
        city_data = validated_data.pop('city', None)
        avatar_file_id = validated_data.pop('avatarFileId', None)

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
    showAvatar = serializers.BooleanField(required=False)
    showGender = serializers.BooleanField(required=False)
    showCity = serializers.BooleanField(required=False)
    showInterests = serializers.BooleanField(required=False)
    showBirthDate = serializers.BooleanField(required=False)
    showAttendanceHistory = serializers.BooleanField(required=False)
    showReviews = serializers.BooleanField(required=False)

    def update(self, instance, validated_data):
        mapping = {
            'showAvatar': 'show_avatar',
            'showGender': 'show_gender',
            'showCity': 'show_city',
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
    avatarFileId = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
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
            'id', 'name', 'avatarFileId', 'rating', 'age', 'gender',
            'city', 'interests', 'attendanceHistory',
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

    def get_avatarFileId(self, obj):
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
        if not (self._is_current_user(obj) or obj.show_reviews):
            return None

        from ratings.models import ActivityRating
        # берём последние 3 отзыва на активности где obj был организатором
        ratings = ActivityRating.objects.filter(
            activity__organizer=obj,
            comment__isnull=False,
        ).select_related('user', 'activity').order_by('-created_at')[:3]

        return [
            {
                'id': str(r.id),
                'fromUserId': str(r.user.id),
                'fromUserName': r.user.name,
                'rating': r.rating,
                'text': r.comment,
                'date': r.created_at.isoformat(),
                'activityId': str(r.activity.id),
            }
            for r in ratings
        ]

class UserSnippetSerializer(serializers.ModelSerializer):
    """Компактный профиль для вложений — карточки активностей, списки участников."""
    id = serializers.CharField()
    avatarFileId = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'name', 'avatarFileId', 'rating']

    def get_avatarFileId(self, obj):
        return str(obj.avatar_file_id) if obj.avatar_file_id else None
