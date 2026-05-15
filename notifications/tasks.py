"""Фоновые задачи для уведомлений.

Все триггеры делают одно — собирают аудиторию и зовут соответствующую фабрику
из `notifications.services`. Сами шаблоны текстов и логика создания живут там.

Делятся на два типа:
- event-based — вызываются `.delay()` из views при действии пользователя
  (создал активность, оставил оценку);
- time-based — запускаются Celery beat по расписанию из CELERY_BEAT_SCHEDULE
  (напоминания, запросы оценки, пометка missed).
"""
from datetime import timedelta

from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import Notification
from .services import (
    notify_activity_reminder,
    notify_new_activity,
    notify_new_review,
    notify_rate_activity,
)


# ============================================================================
# Event-based задачи — триггерятся через .delay() из views
# ============================================================================


@shared_task
def notify_followers_of_new_activity(activity_id):
    """Подписчики организатора получают уведомление о новой активности."""
    from activities.models import Activity
    from subscriptions.models import Subscription

    try:
        activity = Activity.objects.select_related('organizer').get(id=activity_id)
    except Activity.DoesNotExist:
        return

    # KudaGo-события без организатора не порождают уведомлений
    if activity.organizer is None:
        return

    follower_ids = Subscription.objects.filter(
        target=activity.organizer,
    ).values_list('follower_id', flat=True)

    User = get_user_model()
    followers = User.objects.filter(id__in=follower_ids, is_active=True)

    for follower in followers:
        notify_new_activity(
            follower=follower,
            organizer=activity.organizer,
            activity=activity,
        )


@shared_task
def notify_organizer_of_new_rating(rating_id):
    """Организатор получает уведомление о новой оценке его активности."""
    from ratings.models import ActivityRating

    try:
        rating = ActivityRating.objects.select_related(
            'activity__organizer', 'user',
        ).get(id=rating_id)
    except ActivityRating.DoesNotExist:
        return

    organizer = rating.activity.organizer
    if organizer is None or rating.user_id == organizer.id:
        # организатора нет (KudaGo) или сам себя оценил — пропускаем
        return

    notify_new_review(
        organizer=organizer,
        reviewer=rating.user,
        activity=rating.activity,
        rating_value=rating.rating,
    )


# ============================================================================
# Time-based задачи — запускаются Celery beat по расписанию
# ============================================================================


@shared_task
def send_activity_reminders():
    """Напоминание участникам за час до начала активности.

    Beat запускает задачу каждые 5 минут. Берём активности, начинающиеся в
    окне [now+55min; now+65min], и шлём всем accepted-участникам напоминание.
    Дубликаты отсекаются проверкой существующих уведомлений того же типа.
    """
    from activities.models import Activity
    from participation.models import Participation

    now = timezone.now()
    window_start = now + timedelta(minutes=55)
    window_end = now + timedelta(minutes=65)

    activities = Activity.objects.filter(
        status=Activity.Status.ACTIVE,
        start_at__gte=window_start,
        start_at__lte=window_end,
    )

    for activity in activities:
        already_notified = set(Notification.objects.filter(
            activity=activity,
            type=Notification.Type.ACTIVITY_REMINDER,
        ).values_list('user_id', flat=True))

        participations = Participation.objects.filter(
            activity=activity,
            status__in=[
                Participation.Status.ACCEPTED,
                Participation.Status.ATTENDED,
            ],
        ).select_related('user')

        for p in participations:
            if p.user_id in already_notified:
                continue
            notify_activity_reminder(participant=p.user, activity=activity)


@shared_task
def send_rate_requests():
    """Запрос оценки после окончания активности.

    Beat запускает задачу каждые 5 минут. Берём активности, завершившиеся
    за последние ~10 минут, и шлём всем attended-участникам, которые ещё
    не оставили оценку, просьбу её оставить.
    """
    from activities.models import Activity
    from participation.models import Participation
    from ratings.models import ActivityRating

    now = timezone.now()
    activities = Activity.objects.filter(
        status=Activity.Status.ACTIVE,
        end_at__gte=now - timedelta(minutes=10),
        end_at__lte=now,
    )

    for activity in activities:
        already_notified = set(Notification.objects.filter(
            activity=activity,
            type=Notification.Type.RATE_ACTIVITY,
        ).values_list('user_id', flat=True))

        already_rated = set(ActivityRating.objects.filter(
            activity=activity,
        ).values_list('user_id', flat=True))

        participations = Participation.objects.filter(
            activity=activity,
            status=Participation.Status.ATTENDED,
        ).select_related('user')

        for p in participations:
            if p.user_id in already_notified or p.user_id in already_rated:
                continue
            notify_rate_activity(participant=p.user, activity=activity)


@shared_task
def mark_unscanned_as_missed():
    """Перевод accepted → missed для активностей, которые уже закончились.

    Beat запускает задачу каждые 10 минут. Даём 5-минутный буфер организатору
    после end_at — вдруг он ещё доскачет QR. После этого все accepted-участники,
    чей QR не отсканировали, получают статус missed.

    Возвращает количество обновлённых записей (видно в логах воркера).
    """
    from activities.models import Activity
    from participation.models import Participation

    now = timezone.now()
    ended_activity_ids = Activity.objects.filter(
        end_at__lte=now - timedelta(minutes=5),
    ).values_list('id', flat=True)

    updated = Participation.objects.filter(
        activity_id__in=ended_activity_ids,
        status=Participation.Status.ACCEPTED,
    ).update(status=Participation.Status.MISSED)

    return updated
