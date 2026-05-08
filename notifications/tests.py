import pytest
from django.utils import timezone
from rest_framework import status

from notifications.models import DeviceToken, Notification


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
