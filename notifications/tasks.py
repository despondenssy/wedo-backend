"""Фоновые задачи для уведомлений.

Триггеры делятся на два типа:
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


def _create_notification_and_push(
    user, type, title, message, activity=None, request_user=None,
):
    """Создаёт in-app уведомление и шлёт push на устройства пользователя.

    Внутренний helper. Вызывается из задач Celery — латентность FCM здесь
    не блокирует пользовательский запрос, поэтому push шлётся синхронно.
    """
    from .firebase import send_push_to_user

    Notification.objects.create(
        user=user,
        type=type,
        title=title,
        message=message,
        activity=activity,
        request_user=request_user,
        activity_title=activity.title if activity else None,
    )

    data = {'type': type}
    if activity:
        data['activityId'] = str(activity.id)
    send_push_to_user(user, title, message, data=data)


# ============================================================================
# Event-based задачи — триггерятся через .delay() из views
# ============================================================================


@shared_task
def notify_followers_of_new_activity(activity_id):
    """Социальное: пользователь, на которого подписаны, создал активность —
    шлём уведомление всем подписчикам.
    """
    from activities.models import Activity
    from subscriptions.models import Subscription

    try:
        activity = Activity.objects.select_related('organizer').get(id=activity_id)
    except Activity.DoesNotExist:
        return

    follower_ids = Subscription.objects.filter(
        target=activity.organizer,
    ).values_list('follower_id', flat=True)

    User = get_user_model()
    followers = User.objects.filter(id__in=follower_ids, is_active=True)

    for follower in followers:
        _create_notification_and_push(
            user=follower,
            type=Notification.Type.SOCIAL,
            title='Новая активность',
            message=f'{activity.organizer.name} создал(а) «{activity.title}»',
            activity=activity,
            request_user=activity.organizer,
        )


@shared_task
def notify_organizer_of_new_rating(rating_id):
    """Социальное: на твою активность оставили оценку/отзыв —
    шлём уведомление организатору.
    """
    from ratings.models import ActivityRating

    try:
        rating = ActivityRating.objects.select_related(
            'activity__organizer', 'user',
        ).get(id=rating_id)
    except ActivityRating.DoesNotExist:
        return

    organizer = rating.activity.organizer
    if rating.user_id == organizer.id:
        return  # на свою же активность поставил — не уведомляем

    _create_notification_and_push(
        user=organizer,
        type=Notification.Type.SOCIAL,
        title='Новый отзыв',
        message=f'{rating.user.name} оценил(а) «{rating.activity.title}» на {rating.rating}/5',
        activity=rating.activity,
        request_user=rating.user,
    )


# ============================================================================
# Time-based задачи — запускаются Celery beat по расписанию
# ============================================================================


@shared_task
def send_activity_reminders():
    """Напоминание участникам за час до начала активности.

    Beat запускает задачу каждые 5 минут. Берём активности, начинающиеся в
    окне [now+55min; now+65min], и шлём всем accepted-участникам напоминание.
    Дубликаты отсекаются проверкой существующих REMINDER-уведомлений.
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
            type=Notification.Type.REMINDER,
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
            _create_notification_and_push(
                user=p.user,
                type=Notification.Type.REMINDER,
                title='Скоро начнётся',
                message=f'Через час начинается «{activity.title}»',
                activity=activity,
            )


@shared_task
def send_rate_requests():
    """Запрос оценки после окончания активности.

    Beat запускает задачу каждые 5 минут. Берём активности, завершившиеся
    за последние ~10 минут (с запасом), и шлём всем attended-участникам,
    которые ещё не оставили оценку, просьбу её оставить.
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
            type=Notification.Type.RATE_REQUEST,
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
            _create_notification_and_push(
                user=p.user,
                type=Notification.Type.RATE_REQUEST,
                title='Оцените событие',
                message=f'Как вам «{activity.title}»? Поделитесь впечатлением.',
                activity=activity,
            )


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
