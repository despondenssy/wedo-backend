from django.db import models
from django.conf import settings


class Participation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'
        ATTENDED = 'attended', 'Attended'
        REJECTED = 'rejected', 'Rejected'
        MISSED = 'missed', 'Missed'

    activity = models.ForeignKey(
        'activities.Activity',
        on_delete=models.CASCADE,
        related_name='participations',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='participations',
    )
    status = models.CharField(max_length=10, choices=Status.choices)
    attendance_marked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'participations'
        # один пользователь — одна запись на активность
        unique_together = [['activity', 'user']]

    def __str__(self):
        return f'{self.user} → {self.activity} ({self.status})'
