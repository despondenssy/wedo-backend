from unittest.mock import patch

import pytest
from rest_framework import status

from activities.models import UserActivityFeedEvent
from participation.models import Participation


pytestmark = pytest.mark.django_db


def test_join_success_duplicate_requires_approval_full_and_organizer_forbidden(
    auth_client,
    user,
    other_user,
    user_factory,
    activity_factory,
    participation_factory,
):
    open_activity = activity_factory(organizer=other_user)
    joined = auth_client.post(f'/activities/{open_activity.id}/join', {}, format='json')
    assert joined.status_code == status.HTTP_204_NO_CONTENT
    assert Participation.objects.filter(
        activity=open_activity,
        user=user,
        status=Participation.Status.ACCEPTED,
    ).exists()
    assert UserActivityFeedEvent.objects.filter(
        user=user,
        activity=open_activity,
        type='joined',
    ).exists()

    duplicate = auth_client.post(f'/activities/{open_activity.id}/join', {}, format='json')
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    own = activity_factory(organizer=user)
    own_response = auth_client.post(f'/activities/{own.id}/join', {}, format='json')
    assert own_response.status_code == status.HTTP_403_FORBIDDEN

    approval = activity_factory(organizer=other_user, requires_approval=True)
    approval_response = auth_client.post(f'/activities/{approval.id}/join', {}, format='json')
    assert approval_response.status_code == status.HTTP_400_BAD_REQUEST

    # pref_max_participants=2: организатор занимает 1 место, ещё 1 участник — мест нет
    full = activity_factory(organizer=other_user, pref_max_participants=2)
    another_user = user_factory()
    participation_factory(full, another_user, status=Participation.Status.ACCEPTED)
    full_response = auth_client.post(f'/activities/{full.id}/join', {}, format='json')
    assert full_response.status_code == status.HTTP_400_BAD_REQUEST


@patch('participation.views._send_notification')
def test_join_request_list_cancel_approve_and_reject(
    send_notification,
    api_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
):
    activity = activity_factory(organizer=other_user, requires_approval=True)
    api_client.force_authenticate(user=user)
    requested = api_client.post(f'/activities/{activity.id}/join-requests/me', {}, format='json')
    assert requested.status_code == status.HTTP_204_NO_CONTENT
    send_notification.assert_called_once()

    duplicate = api_client.post(f'/activities/{activity.id}/join-requests/me', {}, format='json')
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    cancelled = api_client.delete(f'/activities/{activity.id}/join-requests/me')
    assert cancelled.status_code == status.HTTP_204_NO_CONTENT
    assert not Participation.objects.filter(activity=activity, user=user).exists()

    pending = participation_factory(activity, user, status=Participation.Status.PENDING)
    api_client.force_authenticate(user=other_user)
    approved = api_client.post(
        f'/activities/{activity.id}/join-requests/{user.id}/approve',
        {},
        format='json',
    )
    pending.refresh_from_db()
    assert approved.status_code == status.HTTP_204_NO_CONTENT
    assert pending.status == Participation.Status.ACCEPTED

    pending.status = Participation.Status.PENDING
    pending.save()
    rejected = api_client.post(
        f'/activities/{activity.id}/join-requests/{user.id}/reject',
        {},
        format='json',
    )
    pending.refresh_from_db()
    assert rejected.status_code == status.HTTP_204_NO_CONTENT
    assert pending.status == Participation.Status.REJECTED


def test_approve_reject_require_organizer(api_client, user, other_user, activity_factory, participation_factory):
    activity = activity_factory(organizer=other_user)
    requester = user
    participation_factory(activity, requester, status=Participation.Status.PENDING)
    api_client.force_authenticate(user=requester)

    approve = api_client.post(f'/activities/{activity.id}/join-requests/{requester.id}/approve', {}, format='json')
    reject = api_client.post(f'/activities/{activity.id}/join-requests/{requester.id}/reject', {}, format='json')

    assert approve.status_code == status.HTTP_403_FORBIDDEN
    assert reject.status_code == status.HTTP_403_FORBIDDEN


def test_approve_rejects_when_full(
    api_client,
    user,
    other_user,
    user_factory,
    activity_factory,
    participation_factory,
):
    """Одобрение заявки отклоняется, если нет свободных мест с учётом организатора."""
    activity = activity_factory(organizer=other_user, requires_approval=True, pref_max_participants=2)
    # организатор (other_user) занимает 1 место, ещё 1 участник — мест нет
    another_user = user_factory()
    participation_factory(activity, another_user, status=Participation.Status.ACCEPTED)
    participation_factory(activity, user, status=Participation.Status.PENDING)

    api_client.force_authenticate(user=other_user)
    response = api_client.post(
        f'/activities/{activity.id}/join-requests/{user.id}/approve',
        {},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'ACTIVITY_FULL'


def test_participants_leave_and_manual_attendance(
    api_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
):
    activity = activity_factory(organizer=other_user)
    participation = participation_factory(activity, user, status=Participation.Status.ACCEPTED)
    api_client.force_authenticate(user=other_user)

    participants = api_client.get(f'/activities/{activity.id}/participants')
    assert participants.status_code == status.HTTP_200_OK
    assert participants.json()['items'][0]['user']['id'] == str(user.id)

    attended = api_client.post(
        f'/activities/{activity.id}/attendance',
        {'user_id': user.id},
        format='json',
    )
    participation.refresh_from_db()
    assert attended.status_code == status.HTTP_204_NO_CONTENT
    assert participation.status == Participation.Status.ATTENDED
    assert participation.attendance_marked_at is not None
    assert UserActivityFeedEvent.objects.filter(
        user=user,
        activity=activity,
        type='attended',
    ).exists()

    accepted = participation_factory(activity_factory(organizer=other_user), user, status=Participation.Status.ACCEPTED)
    api_client.force_authenticate(user=user)
    left = api_client.delete(f'/activities/{accepted.activity_id}/participants/me')
    assert left.status_code == status.HTTP_204_NO_CONTENT
    assert not Participation.objects.filter(id=accepted.id).exists()
    assert UserActivityFeedEvent.objects.filter(
        user=user,
        activity=accepted.activity,
        type='leaved',
    ).exists()


def test_manual_attendance_requires_organizer_and_user_id(
    auth_client,
    user,
    other_user,
    activity_factory,
):
    activity = activity_factory(organizer=other_user)

    forbidden = auth_client.post(f'/activities/{activity.id}/attendance', {'user_id': user.id}, format='json')
    missing_user = auth_client.post(f'/activities/{activity.id}/attendance', {}, format='json')

    assert forbidden.status_code == status.HTTP_403_FORBIDDEN
    assert missing_user.status_code == status.HTTP_403_FORBIDDEN


def test_participation_endpoint_requires_auth(api_client, activity):
    response = api_client.post(f'/activities/{activity.id}/join', {}, format='json')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_join_requests_list_organizer_sees_pending(
    auth_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
):
    """Организатор видит список pending заявок."""
    activity = activity_factory(organizer=user, requires_approval=True)
    participation_factory(activity, other_user, status=Participation.Status.PENDING)

    response = auth_client.get(f'/activities/{activity.id}/join-requests')

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data['items']) == 1
    assert data['items'][0]['user']['id'] == str(other_user.id)
    assert data['items'][0]['participation_status'] == 'pending'
    assert data['has_more'] is False
    assert data['next_cursor'] is None


def test_join_requests_list_non_organizer_forbidden(
    api_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
):
    """Не-организатор получает 403."""
    activity = activity_factory(organizer=other_user, requires_approval=True)
    participation_factory(activity, user, status=Participation.Status.PENDING)
    api_client.force_authenticate(user=user)

    response = api_client.get(f'/activities/{activity.id}/join-requests')

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()['error']['code'] == 'FORBIDDEN'


def test_join_requests_list_empty(
    auth_client,
    user,
    activity_factory,
):
    """Нет pending заявок — пустой список."""
    activity = activity_factory(organizer=user)

    response = auth_client.get(f'/activities/{activity.id}/join-requests')

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['items'] == []
    assert data['has_more'] is False
    assert data['next_cursor'] is None


def test_join_requests_list_pagination(
    auth_client,
    user,
    user_factory,
    activity_factory,
    participation_factory,
):
    """Cursor-пагинация: limit работает, has_more и next_cursor возвращаются."""
    activity = activity_factory(organizer=user, requires_approval=True)
    for _ in range(5):
        participant = user_factory()
        participation_factory(activity, participant, status=Participation.Status.PENDING)

    response = auth_client.get(f'/activities/{activity.id}/join-requests', {'limit': 2})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data['items']) == 2
    assert data['has_more'] is True
    assert data['next_cursor'] is not None

    # Долистываем до конца
    while data['next_cursor']:
        response = auth_client.get(
            f'/activities/{activity.id}/join-requests',
            {'limit': 2, 'cursor': data['next_cursor']},
        )
        data = response.json()
    assert len(data['items']) <= 2
    assert data['has_more'] is False
    assert data['next_cursor'] is None


def test_join_requests_list_requires_auth(api_client, activity):
    """Без аутентификации — 401."""
    response = api_client.get(f'/activities/{activity.id}/join-requests')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
