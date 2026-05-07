from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from participation.models import Participation
from users.models import QrToken, User


pytestmark = pytest.mark.django_db


def register_payload(email='new@example.com'):
    return {
        'name': 'New User',
        'email': email,
        'password': 'StrongPass123',
        'birthDate': '1998-05-20',
        'gender': 'female',
        'city': {
            'settlement': 'Moscow',
            'region': 'Moscow',
            'country': 'Russia',
            'latitude': 55.75,
            'longitude': 37.61,
            'title': 'Moscow',
        },
        'interests': ['sport'],
        'showBirthDate': True,
    }


def test_register_login_refresh_and_logout(api_client, user_factory):
    response = api_client.post('/auth/register', register_payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body['user']['showBirthDate'] is True
    assert body['tokens']['accessToken']
    assert User.objects.filter(email='new@example.com').exists()
    user = User.objects.get(email='new@example.com')
    assert user.show_birth_date is True

    login = api_client.post(
        '/auth/login',
        {'email': 'new@example.com', 'password': 'StrongPass123'},
        format='json',
    )
    assert login.status_code == status.HTTP_200_OK
    login_body = login.json()
    assert login_body['tokens']['refreshToken']

    refresh = api_client.post(
        '/auth/refresh',
        {'refreshToken': login_body['tokens']['refreshToken']},
        format='json',
    )
    assert refresh.status_code == status.HTTP_200_OK
    assert refresh.json()['accessToken']

    api_client.force_authenticate(user=user)
    logout = api_client.post(
        '/auth/logout',
        {'refreshToken': login_body['tokens']['refreshToken']},
        format='json',
    )
    assert logout.status_code == status.HTTP_204_NO_CONTENT


def test_register_requires_show_birth_date(api_client):
    payload = register_payload()
    payload.pop('showBirthDate')

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'showBirthDate' in response.json()


def test_register_rejects_short_password(api_client):
    payload = register_payload()
    payload['password'] = 'Abc12'  # 5 символов — короче минимума 8

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'password' in response.json()


def test_register_rejects_numeric_only_password(api_client):
    payload = register_payload()
    payload['password'] = '12345678'  # только цифры — NumericPasswordValidator

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'password' in response.json()


def test_register_rejects_common_password(api_client):
    payload = register_payload()
    payload['password'] = 'password'  # из списка топ-распространённых — CommonPasswordValidator

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'password' in response.json()


def test_login_and_refresh_reject_invalid_data(api_client, user):
    bad_login = api_client.post(
        '/auth/login',
        {'email': user.email, 'password': 'wrong'},
        format='json',
    )
    assert bad_login.status_code == status.HTTP_401_UNAUTHORIZED

    no_refresh = api_client.post('/auth/refresh', {}, format='json')
    assert no_refresh.status_code == status.HTTP_400_BAD_REQUEST

    bad_refresh = api_client.post('/auth/refresh', {'refreshToken': 'bad'}, format='json')
    assert bad_refresh.status_code == status.HTTP_401_UNAUTHORIZED


def test_me_get_patch_show_birth_date_and_delete(auth_client, user):
    get_response = auth_client.get('/me')
    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json()['isCurrentUser'] is True

    patch_response = auth_client.patch(
        '/me',
        {
            'name': 'Updated',
            'city': {
                'settlement': 'Saint Petersburg',
                'region': 'Saint Petersburg',
                'country': 'Russia',
                'latitude': 59.93,
                'longitude': 30.31,
                'title': 'SPb',
            },
            'interests': ['music'],
            'showBirthDate': True,
        },
        format='json',
    )
    user.refresh_from_db()
    assert patch_response.status_code == status.HTTP_200_OK
    assert user.name == 'Updated'
    assert user.city_settlement == 'Saint Petersburg'
    assert user.show_birth_date is True
    assert patch_response.json()['showBirthDate'] is True

    delete_response = auth_client.delete('/me')
    user.refresh_from_db()
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    assert user.is_active is False
    assert user.deleted_at is not None




def test_user_history_my_activities_rating_and_attendance(
    auth_client,
    user,
    activity_factory,
    participation_factory,
):
    created = activity_factory(organizer=user)
    attended = activity_factory()
    missed = activity_factory()
    participation_factory(attended, user, status=Participation.Status.ATTENDED)
    participation_factory(missed, user, status=Participation.Status.MISSED)

    created_response = auth_client.get(f'/users/{user.id}/history?tab=created')
    assert created_response.status_code == status.HTTP_200_OK
    assert str(created.id) in [item['id'] for item in created_response.json()['items']]

    mine = auth_client.get('/me/my-activities')
    assert mine.status_code == status.HTTP_200_OK
    assert 'items' in mine.json()

    rating = auth_client.get(f'/users/{user.id}/rating')
    assert rating.status_code == status.HTTP_200_OK
    assert rating.json() == {'rating': user.rating}

    attendance = auth_client.get(f'/users/{user.id}/attendance-history')
    assert attendance.status_code == status.HTTP_200_OK
    assert attendance.json() == {'attended': 1, 'missed': 1}

    invalid_tab = auth_client.get(f'/users/{user.id}/history?tab=bad')
    assert invalid_tab.status_code == status.HTTP_400_BAD_REQUEST


def test_qr_token_resolve_and_scan(
    auth_client,
    api_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
    qr_token_factory,
):
    created = auth_client.post('/me/qr-token', {}, format='json')
    assert created.status_code == status.HTTP_200_OK
    created_body = created.json()
    assert 'expiresAt' in created_body
    assert QrToken.objects.filter(user=user).count() == 1

    resolver = api_client
    resolver.force_authenticate(user=other_user)
    resolved = resolver.post('/qr-tokens/resolve', {'token': created_body['token']}, format='json')
    assert resolved.status_code == status.HTTP_200_OK
    assert resolved.json()['user']['id'] == str(user.id)

    activity = activity_factory(organizer=other_user)
    participation = participation_factory(activity, user, status=Participation.Status.ACCEPTED)
    scanned = resolver.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': created_body['token']},
        format='json',
    )
    participation.refresh_from_db()
    assert scanned.status_code == status.HTTP_204_NO_CONTENT
    assert participation.status == Participation.Status.ATTENDED
    assert participation.attendance_marked_at is not None

    expired = qr_token_factory(
        user=user,
        token='qr:expired',
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    expired_response = resolver.post('/qr-tokens/resolve', {'token': expired.token}, format='json')
    assert expired_response.status_code == status.HTTP_400_BAD_REQUEST


def test_qr_scan_requires_organizer(auth_client, user, other_user, activity_factory, qr_token_factory):
    activity = activity_factory(organizer=other_user)
    token = qr_token_factory(user=user)

    response = auth_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': token.token},
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_qr_resolve_rejects_used_token(api_client, user, other_user, qr_token_factory):
    used = qr_token_factory(
        user=user,
        token='qr:used',
        used_at=timezone.now(),
    )
    api_client.force_authenticate(user=other_user)

    response = api_client.post('/qr-tokens/resolve', {'token': used.token}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'TOKEN_USED'


def test_qr_scan_rejects_used_token(
    api_client,
    user,
    other_user,
    activity_factory,
    participation_factory,
    qr_token_factory,
):
    activity = activity_factory(organizer=other_user)
    participation_factory(activity, user, status=Participation.Status.ACCEPTED)
    used = qr_token_factory(
        user=user,
        token='qr:scan-used',
        used_at=timezone.now(),
    )
    api_client.force_authenticate(user=other_user)

    response = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': used.token},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'TOKEN_USED'


def test_protected_user_endpoint_requires_auth(api_client, user):
    response = api_client.get('/me')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
