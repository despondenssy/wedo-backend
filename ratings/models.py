from django.db import models
from django.conf import settings


class ActivityRating(models.Model):
    activity = models.ForeignKey(
        'activities.Activity',
        on_delete=models.CASCADE,
        related_name='ratings',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ratings',
    )
    rating = models.IntegerField()
    comment = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'activity_ratings'
        # один пользователь — одна оценка на активность
        unique_together = [['activity', 'user']]

    def __str__(self):
        return f'{self.user} → {self.activity} ({self.rating})'
