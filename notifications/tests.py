from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from notifications.models import DeviceToken, Notification
from participation.models import Participation


pytestmark = pytest.mark.django_db


def test_notifications_list_filters_mark_read_unread_read_all_and_delete(
    api_client,
    auth_client,
    user,
    other_user,
    notification_factory,
):
    unread = notification_factory(user, type=Notification.Type.SYSTEM, title='Unread')
    read = notification_factory(user, type=Notification.Type.REQUEST, title='Read', read_at=timezone.now())
    notification_factory(other_user, type=Notification.Type.SYSTEM)

    list_response = auth_client.get('/me/notifications?unread_only=true&type=system')
    assert list_response.status_code == status.HTTP_200_OK
    assert [item['id'] for item in list_response.json()['items']] == [str(unread.id)]

    marked = auth_client.patch(f'/notifications/{unread.id}', {'read': True}, format='json')
    unread.refresh_from_db()
    assert marked.status_code == status.HTTP_200_OK
    assert unread.read_at is not None
    assert marked.json()['read'] is True

    unread_again = auth_client.patch(f'/notifications/{unread.id}', {'read': False}, format='json')
    unread.refresh_from_db()
    assert unread_again.status_code == status.HTTP_200_OK
    assert unread.read_at is None

    all_read = auth_client.post('/notifications/read-all', {}, format='json')
    unread.refresh_from_db()
    assert all_read.status_code == status.HTTP_204_NO_CONTENT
    assert unread.read_at is not None

    api_client.force_authenticate(user=other_user)
    forbidden = api_client.patch(f'/notifications/{read.id}', {'read': True}, format='json')
    assert forbidden.status_code == status.HTTP_404_NOT_FOUND

    api_client.force_authenticate(user=user)
    deleted = api_client.delete(f'/notifications/{read.id}')
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not Notification.objects.filter(id=read.id).exists()


def test_device_token_create_update_and_validation(auth_client, user, other_user, api_client):
    missing = auth_client.post('/me/device-token', {}, format='json')
    assert missing.status_code == status.HTTP_400_BAD_REQUEST

    created = auth_client.post('/me/device-token', {'token': 'fcm-token'}, format='json')
    assert created.status_code == status.HTTP_204_NO_CONTENT
    token = DeviceToken.objects.get(token='fcm-token')
    assert token.user == user

    api_client.force_authenticate(user=other_user)
    moved = api_client.post('/me/device-token', {'token': 'fcm-token'}, format='json')
    token.refresh_from_db()
    assert moved.status_code == status.HTTP_204_NO_CONTENT
    assert token.user == other_user


def test_notifications_endpoint_requires_auth(api_client):
    response = api_client.get('/me/notifications')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ============================================================================
# Тесты для Celery-задач уведомлений
# ============================================================================


def test_notify_followers_of_new_activity_creates_notifications_only_for_subscribers(
    user_factory,
    activity_factory,
    subscription_factory,
):
    from notifications.tasks import notify_followers_of_new_activity

    organizer = user_factory()
    follower = user_factory()
    not_follower = user_factory()
    subscription_factory(follower=follower, target=organizer)

    activity = activity_factory(organizer=organizer, title='Йога на закате')

    notify_followers_of_new_activity(activity.id)

    # подписчик получил уведомление
    assert Notification.objects.filter(
        user=follower,
        type=Notification.Type.SOCIAL,
        activity=activity,
    ).exists()
    # неподписчик — нет
    assert not Notification.objects.filter(user=not_follower).exists()


def test_notify_organizer_of_new_rating_creates_notification(
    user, activity_factory, participation_factory, rating_factory,
):
    from notifications.tasks import notify_organizer_of_new_rating

    activity = activity_factory()  # organizer = свежий user из factory
    participation_factory(activity, user, status=Participation.Status.ATTENDED)
    rating = rating_factory(activity, user, rating=4, comment='Norm')

    notify_organizer_of_new_rating(rating.id)

    notif = Notification.objects.get(
        user=activity.organizer,
        type=Notification.Type.SOCIAL,
        activity=activity,
    )
    assert '4/5' in notif.message


def test_send_activity_reminders_sends_once_to_accepted_participants(
    user_factory, activity_factory, participation_factory,
):
    from notifications.tasks import send_activity_reminders

    # активность начнётся через ~час — попадает в окно [55; 65] мин
    in_an_hour = timezone.now() + timedelta(minutes=60)
    activity = activity_factory(
        start_at=in_an_hour,
        end_at=in_an_hour + timedelta(hours=2),
    )

    accepted = user_factory()
    pending = user_factory()
    rejected = user_factory()
    participation_factory(activity, accepted, status=Participation.Status.ACCEPTED)
    participation_factory(activity, pending, status=Participation.Status.PENDING)
    participation_factory(activity, rejected, status=Participation.Status.REJECTED)

    send_activity_reminders()

    # accepted получил
    assert Notification.objects.filter(
        user=accepted, type=Notification.Type.REMINDER, activity=activity,
    ).exists()
    # pending и rejected — нет
    assert not Notification.objects.filter(user=pending).exists()
    assert not Notification.objects.filter(user=rejected).exists()

    # повторный вызов не плодит дубли
    send_activity_reminders()
    assert Notification.objects.filter(
        user=accepted, type=Notification.Type.REMINDER, activity=activity,
    ).count() == 1


def test_send_rate_requests_skips_users_who_already_rated(
    user_factory, activity_factory, participation_factory, rating_factory,
):
    from notifications.tasks import send_rate_requests

    # активность только что закончилась
    just_ended = activity_factory(
        start_at=timezone.now() - timedelta(hours=2),
        end_at=timezone.now() - timedelta(minutes=2),
    )

    rated_user = user_factory()
    not_rated_user = user_factory()
    participation_factory(just_ended, rated_user, status=Participation.Status.ATTENDED)
    participation_factory(just_ended, not_rated_user, status=Participation.Status.ATTENDED)
    rating_factory(just_ended, rated_user, rating=5)

    send_rate_requests()

    # тот, кто ещё не оценил — получает запрос
    assert Notification.objects.filter(
        user=not_rated_user, type=Notification.Type.RATE_REQUEST,
    ).exists()
    # тот, кто уже оценил — не получает
    assert not Notification.objects.filter(
        user=rated_user, type=Notification.Type.RATE_REQUEST,
    ).exists()


def test_mark_unscanned_as_missed_updates_only_accepted_for_ended_activities(
    user_factory, activity_factory, participation_factory,
):
    from notifications.tasks import mark_unscanned_as_missed

    # активность закончилась 10 минут назад
    ended = activity_factory(
        start_at=timezone.now() - timedelta(hours=2),
        end_at=timezone.now() - timedelta(minutes=10),
    )
    accepted_user = user_factory()
    attended_user = user_factory()
    p_accepted = participation_factory(ended, accepted_user, status=Participation.Status.ACCEPTED)
    p_attended = participation_factory(ended, attended_user, status=Participation.Status.ATTENDED)

    # активность ещё идёт — не должно тронуться
    ongoing = activity_factory(
        start_at=timezone.now() - timedelta(minutes=10),
        end_at=timezone.now() + timedelta(hours=1),
    )
    ongoing_user = user_factory()
    p_ongoing = participation_factory(ongoing, ongoing_user, status=Participation.Status.ACCEPTED)

    mark_unscanned_as_missed()

    p_accepted.refresh_from_db()
    p_attended.refresh_from_db()
    p_ongoing.refresh_from_db()

    assert p_accepted.status == Participation.Status.MISSED
    # attended не трогаем — у них всё ок
    assert p_attended.status == Participation.Status.ATTENDED
    # активность ещё идёт — не трогаем
    assert p_ongoing.status == Participation.Status.ACCEPTED
