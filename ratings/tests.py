import pytest
from rest_framework import status

from activities.models import UserActivityFeedEvent
from participation.models import Participation
from ratings.models import ActivityRating


pytestmark = pytest.mark.django_db


def test_rating_list_create_recalculate_and_duplicate(
    auth_client,
    user,
    activity_factory,
    participation_factory,
):
    activity = activity_factory()
    participation_factory(activity, user, status=Participation.Status.ATTENDED)

    created = auth_client.post(
        f'/activities/{activity.id}/ratings',
        {'rating': 5, 'comment': 'Excellent'},
        format='json',
    )
    activity.organizer.refresh_from_db()

    assert created.status_code == status.HTTP_201_CREATED
    assert ActivityRating.objects.filter(activity=activity, user=user).exists()
    assert UserActivityFeedEvent.objects.filter(user=user, activity=activity, type='rated').exists()
    assert activity.organizer.rating > 0

    duplicate = auth_client.post(
        f'/activities/{activity.id}/ratings',
        {'rating': 4},
        format='json',
    )
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    list_response = auth_client.get(f'/activities/{activity.id}/ratings')
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json()['items'][0]['rating'] == 5


def test_rating_requires_attendance_and_valid_value(auth_client, activity):
    not_attended = auth_client.post(f'/activities/{activity.id}/ratings', {'rating': 5}, format='json')
    assert not_attended.status_code == status.HTTP_403_FORBIDDEN

    invalid_activity = activity
    Participation.objects.create(activity=invalid_activity, user=auth_client.handler._force_user, status='attended')
    invalid = auth_client.post(f'/activities/{invalid_activity.id}/ratings', {'rating': 6}, format='json')
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST


def test_ratings_endpoint_requires_auth(api_client, activity):
    response = api_client.get(f'/activities/{activity.id}/ratings')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
