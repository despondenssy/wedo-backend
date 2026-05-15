from django.db import models
from django.conf import settings


class Notification(models.Model):
    class Type(models.TextChoices):
        # действия с заявками
        JOIN_REQUEST = 'join_request', 'Join Request'
        JOIN_REQUEST_APPROVED = 'join_request_approved', 'Join Request Approved'
        JOIN_REQUEST_REJECTED = 'join_request_rejected', 'Join Request Rejected'
        # жизненный цикл активности
        ACTIVITY_REMINDER = 'activity_reminder', 'Activity Reminder'
        NEW_ACTIVITY = 'new_activity', 'New Activity'
        ACTIVITY_CANCELLED = 'activity_cancelled', 'Activity Cancelled'
        ORGANIZER_ASSIGNED = 'organizer_assigned', 'Organizer Assigned'
        # оценки
        RATE_ACTIVITY = 'rate_activity', 'Rate Activity'
        NEW_REVIEW = 'new_review', 'New Review'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    type = models.CharField(max_length=30, choices=Type.choices)
    title = models.CharField(max_length=255)
    message = models.TextField()
    read_at = models.DateTimeField(blank=True, null=True)
    activity = models.ForeignKey(
        'activities.Activity',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    # пользователь, из-за действия которого появилось уведомление:
    # для заявки — заявитель, для new_activity — организатор, для new_review — автор оценки
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='triggered_notifications',
    )
    action_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            # /me/notifications: основная сортировка
            models.Index(fields=['user', '-created_at']),
            # фильтр unreadOnly=true
            models.Index(fields=['user', 'read_at']),
        ]

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
