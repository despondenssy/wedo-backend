from django.db import models
from django.conf import settings


class Notification(models.Model):
    class Type(models.TextChoices):
        REQUEST = 'request', 'Request'
        SYSTEM = 'system', 'System'
        REMINDER = 'reminder', 'Reminder'
        SOCIAL = 'social', 'Social'
        REQUEST_APPROVED = 'request_approved', 'Request Approved'
        REQUEST_REJECTED = 'request_rejected', 'Request Rejected'
        RATE_REQUEST = 'rate_request', 'Rate Request'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    read_at = models.DateTimeField(blank=True, null=True)
    activity = models.ForeignKey(
        'activities.Activity',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    request_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='triggered_notifications',
    )
    activity_title = models.CharField(max_length=255, blank=True, null=True)
    action_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.title}'

    @property
    def is_read(self):
        return self.read_at is not None


class DeviceToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='device_tokens',
    )
    token = models.TextField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'device_tokens'

    def __str__(self):
        return f'{self.user} — {self.token[:20]}...'
