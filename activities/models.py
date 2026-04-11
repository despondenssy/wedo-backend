from django.db import models
from django.conf import settings


class Activity(models.Model):
    class Format(models.TextChoices):
        ONLINE = 'online', 'Online'
        OFFLINE = 'offline', 'Offline'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        CANCELLED = 'cancelled', 'Cancelled'

    class Level(models.TextChoices):
        BEGINNER = 'beginner', 'Beginner'
        INTERMEDIATE = 'intermediate', 'Intermediate'
        ADVANCED = 'advanced', 'Advanced'

    class Gender(models.TextChoices):
        MALE = 'male', 'Male'
        FEMALE = 'female', 'Female'

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='organized_activities',
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    category_id = models.CharField(max_length=100)
    subcategory_id = models.CharField(max_length=100, blank=True, null=True)

    format = models.CharField(max_length=10, choices=Format.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    # location
    location_latitude = models.FloatField()
    location_longitude = models.FloatField()
    location_address = models.CharField(max_length=500)
    location_name = models.CharField(max_length=255, blank=True, null=True)
    location_settlement = models.CharField(max_length=255, blank=True, null=True)

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    time_zone = models.CharField(max_length=100, default='UTC')

    # preferences
    pref_gender = models.CharField(max_length=10, choices=Gender.choices, blank=True, null=True)
    pref_age_from = models.IntegerField(blank=True, null=True)
    pref_age_to = models.IntegerField(blank=True, null=True)
    pref_level = models.CharField(max_length=20, choices=Level.choices, blank=True, null=True)
    pref_max_participants = models.IntegerField(blank=True, null=True)

    requires_approval = models.BooleanField(default=False)
    photo_file_ids = models.JSONField(default=list, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'activities'
        ordering = ['-created_at']
        verbose_name = 'Activity'
        verbose_name_plural = 'Activities'

    def __str__(self):
        return self.title

    @property
    def location(self):
        return {
            'latitude': self.location_latitude,
            'longitude': self.location_longitude,
            'address': self.location_address,
            'name': self.location_name,
            'settlement': self.location_settlement,
        }

    @property
    def preferences(self):
        prefs = {}
        if self.pref_gender:
            prefs['gender'] = self.pref_gender
        if self.pref_age_from is not None:
            prefs['ageFrom'] = self.pref_age_from
        if self.pref_age_to is not None:
            prefs['ageTo'] = self.pref_age_to
        if self.pref_level:
            prefs['level'] = self.pref_level
        if self.pref_max_participants is not None:
            prefs['maxParticipants'] = self.pref_max_participants
        return prefs if prefs else None
