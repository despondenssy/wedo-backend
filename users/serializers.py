from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password as django_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

User = get_user_model()


class CitySerializer(serializers.Serializer):
    settlement = serializers.CharField()
    region = serializers.CharField()
    country = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    title = serializers.CharField(required=False, allow_blank=True)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    city = CitySerializer()
    show_birth_date = serializers.BooleanField(required=True)

    class Meta:
        model = User
        fields = ['name', 'email', 'password', 'birth_date', 'gender', 'city', 'interests', 'show_birth_date']

    def validate_password(self, value):
        # прогоняем через AUTH_PASSWORD_VALIDATORS из settings:
        # минимальная длина, общие пароли, только-цифры, похожесть на email/имя
        temp_user = User(
            email=self.initial_data.get('email', ''),
            name=self.initial_data.get('name', ''),
        )
        try:
            django_validate_password(value, user=temp_user)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

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
    avatar_file_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

    class Meta:
        model = User
        fields = ['name', 'avatar_file_id', 'birth_date', 'gender', 'city', 'interests', 'show_birth_date']
        extra_kwargs = {
            'name': {'required': False},
            'birth_date': {'required': False},
            'gender': {'required': False},
            'interests': {'required': False},
            'show_birth_date': {'required': False},
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


class UserProfileSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    avatar_file_id = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
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
            'id', 'name', 'avatar_file_id', 'rating', 'age', 'gender', 'show_birth_date',
            'city', 'interests', 'attendance_history',
            'reviews_preview', 'is_current_user', 'is_subscribed',
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
        return str(obj.avatar_file_id) if obj.avatar_file_id else None

    def get_age(self, obj):
        if self._is_current_user(obj) or obj.show_birth_date:
            return obj.age
        return None

    def get_gender(self, obj):
        return obj.gender

    def get_city(self, obj):
        return obj.city

    def get_interests(self, obj):
        return obj.interests

    def get_attendance_history(self, obj):
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
