from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.conf import settings

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email обязателен')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Gender(models.TextChoices):
        MALE = 'male', 'Male'
        FEMALE = 'female', 'Female'
        NOT_GIVEN = 'notgiven', 'Not given'

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    birth_date = models.DateField()
    gender = models.CharField(max_length=10, choices=Gender.choices, default=Gender.NOT_GIVEN)
    avatar_file = models.ForeignKey(
        'files.File',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='user_avatars',
    )
    rating = models.FloatField(default=0.0)
    interests = models.JSONField(default=list, blank=True)
    social_link = models.URLField(max_length=500, blank=True, null=True)
    about_me = models.TextField(max_length=1000, blank=True, null=True)

    # city
    city_settlement = models.CharField(max_length=255, blank=True, null=True)
    city_region = models.CharField(max_length=255, blank=True, null=True)
    city_country = models.CharField(max_length=255, blank=True, null=True)
    city_latitude = models.FloatField(blank=True, null=True)
    city_longitude = models.FloatField(blank=True, null=True)
    city_title = models.CharField(max_length=255, blank=True, null=True)

    # privacy
    show_birth_date = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'birth_date', 'gender']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email

    @property
    def age(self):
        from datetime import date
        today = date.today()
        b = self.birth_date
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))

    @property
    def city(self):
        return {
            'settlement': self.city_settlement,
            'region': self.city_region,
            'country': self.city_country,
            'latitude': self.city_latitude,
            'longitude': self.city_longitude,
            'title': self.city_title,
        }

class QrToken(models.Model):
    token = models.CharField(max_length=255, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='qr_tokens',
    )
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'qr_tokens'

    def __str__(self):
        return f'{self.user} — {self.token}'

    @property
    def is_expired(self):
        from django.utils import timezone
        if self.expires_at is None: #если expires_at пустое, выкидывал ошибку
            return False
        return timezone.now() > self.expires_at
