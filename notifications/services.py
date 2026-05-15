"""Единый сервис создания уведомлений.

Все места которые создают `Notification` ходят через `create_notification(...)`.
Прямой `Notification.objects.create(...)` вне этого модуля запрещён —
шаблоны текстов хранятся здесь централизованно, как и отправка push.

API устроено так:
- есть набор фабрик `notify_*(actor, target, activity, ...)`, по одной на каждый
  тип. Они формируют title/message и зовут общий `create_notification`.
- `create_notification` создаёт запись в БД и шлёт FCM-push с одинаковыми
  title/message и payload'ом в camelCase.
"""
from __future__ import annotations

from .models import Notification


# ---------------------------------------------------------------------------
# Гендерные формы глаголов — для шаблонов текстов уведомлений
# ---------------------------------------------------------------------------

def gendered_verb(gender, *, male, female, neutral):
    """Возвращает форму глагола под гендер пользователя.

    male → male, female → female, notgiven/любой другой → neutral.
    Пример: gendered_verb(u.gender, male='создал', female='создала', neutral='создал(а)')
    """
    if gender == 'male':
        return male
    if gender == 'female':
        return female
    return neutral


# ---------------------------------------------------------------------------
# Общий create_notification — единственная точка создания
# ---------------------------------------------------------------------------

def create_notification(
    *,
    user,
    type,
    title,
    message,
    activity=None,
    actor_user=None,
    action_required=False,
):
    """Создаёт запись Notification + шлёт FCM-push.

    Push отправляется синхронно — обычно вызывается из Celery-задачи или
    инлайн из view, где небольшая задержка приемлема.
    """
    from .firebase import send_push_to_user

    notif = Notification.objects.create(
        user=user,
        type=type,
        title=title,
        message=message,
        activity=activity,
        actor_user=actor_user,
        action_required=action_required,
    )

    # FCM требует чтобы все значения в data были строками
    push_data = {
        'notification_id': str(notif.id),
        'type': type,
    }
    if activity is not None:
        push_data['activity_id'] = str(activity.id)
    if actor_user is not None:
        push_data['actor_user_id'] = str(actor_user.id)

    send_push_to_user(user, title, message, data=push_data)
    return notif


# ---------------------------------------------------------------------------
# Фабрики по типу — формируют title/message и вызывают create_notification
# ---------------------------------------------------------------------------

def notify_join_request(*, organizer, applicant, activity):
    """Поступила новая заявка → организатору."""
    return create_notification(
        user=organizer,
        type=Notification.Type.JOIN_REQUEST,
        title='Новая заявка',
        message=f'{applicant.name} хочет присоединиться к «{activity.title}»',
        activity=activity,
        actor_user=applicant,
        action_required=True,
    )


def notify_join_request_approved(*, applicant, activity):
    """Заявка одобрена → заявителю."""
    return create_notification(
        user=applicant,
        type=Notification.Type.JOIN_REQUEST_APPROVED,
        title='Заявка одобрена',
        message=f'Вы стали участником «{activity.title}»',
        activity=activity,
        actor_user=activity.organizer,
    )


def notify_join_request_rejected(*, applicant, activity):
    """Заявка отклонена → заявителю."""
    return create_notification(
        user=applicant,
        type=Notification.Type.JOIN_REQUEST_REJECTED,
        title='Заявка отклонена',
        message=f'В этот раз попасть на «{activity.title}» не получилось',
        activity=activity,
        actor_user=activity.organizer,
    )


def notify_activity_reminder(*, participant, activity):
    """За час до начала → участнику."""
    return create_notification(
        user=participant,
        type=Notification.Type.ACTIVITY_REMINDER,
        title='Скоро начнётся',
        message=f'До начала «{activity.title}» остался час',
        activity=activity,
    )


def notify_new_activity(*, follower, organizer, activity):
    """Подписанный создал новую активность → подписчику."""
    verb = gendered_verb(
        organizer.gender, male='создал', female='создала', neutral='создал(а)',
    )
    return create_notification(
        user=follower,
        type=Notification.Type.NEW_ACTIVITY,
        title='Новая активность',
        message=f'{organizer.name} {verb} новую активность «{activity.title}»',
        activity=activity,
        actor_user=organizer,
    )


def notify_rate_activity(*, participant, activity):
    """После окончания → попроси оценить."""
    return create_notification(
        user=participant,
        type=Notification.Type.RATE_ACTIVITY,
        title='Оцените активность',
        message=f'Как вам «{activity.title}»? Поделитесь впечатлениями',
        activity=activity,
        action_required=True,
    )


def notify_activity_cancelled(*, recipient, activity):
    """Активность отменена → участнику или pending-заявителю."""
    return create_notification(
        user=recipient,
        type=Notification.Type.ACTIVITY_CANCELLED,
        title='Активность отменена',
        message=f'«{activity.title}» не состоится',
        activity=activity,
    )


def notify_new_review(*, organizer, reviewer, activity, rating_value):
    """Оставили оценку → организатору."""
    verb = gendered_verb(
        reviewer.gender, male='оценил', female='оценила', neutral='оценил(а)',
    )
    return create_notification(
        user=organizer,
        type=Notification.Type.NEW_REVIEW,
        title='Новый отзыв',
        message=(
            f'{reviewer.name} {verb} Вашу активность «{activity.title}» '
            f'на {rating_value}★'
        ),
        activity=activity,
        actor_user=reviewer,
    )


def notify_organizer_assigned(*, new_organizer, activity):
    """Организаторство передано → новому организатору."""
    return create_notification(
        user=new_organizer,
        type=Notification.Type.ORGANIZER_ASSIGNED,
        title='Вы стали организатором',
        message=f'Организация события «{activity.title}» перешла к Вам',
        activity=activity,
        action_required=True,
    )
