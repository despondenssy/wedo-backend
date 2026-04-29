import pytest
from rest_framework.test import APIClient
from rest_framework import status

from activities.models import Activity, SavedActivity
from participation.models import Participation


pytestmark = pytest.mark.django_db


def test_activity_list_filters_pagination_and_requires_auth(api_client, auth_client, activity_factory):
    football = activity_factory(category_id='sport', subcategory_id='football', location_settlement='Moscow')
    activity_factory(category_id='music', subcategory_id='guitar', location_settlement='Kazan')

    unauth = APIClient().get('/activities')
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    response = auth_client.get('/activities?categoryId=sport&citySettlement=Moscow&limit=1')
    assert response.status_code == status.HTTP_200_OK
    assert response.data['items'][0]['id'] == str(football.id)
    assert response.data['hasMore'] is False
    assert response.data['nextCursor'] is None


def test_activity_detail_patch_delete_cancel_and_permissions(
    api_client,
    auth_client,
    user,
    other_user,
    activity_factory,
):
    activity = activity_factory(organizer=user)

    detail = auth_client.get(f'/activities/{activity.id}')
    assert detail.status_code == status.HTTP_200_OK
    assert detail.data['policyFlags']['canEdit'] is True

    patched = auth_client.patch(f'/activities/{activity.id}', {'title': 'Renamed'}, format='json')
    activity.refresh_from_db()
    assert patched.status_code == status.HTTP_200_OK
    assert activity.title == 'Renamed'

    api_client.force_authenticate(user=other_user)
    forbidden_patch = api_client.patch(f'/activities/{activity.id}', {'title': 'Nope'}, format='json')
    assert forbidden_patch.status_code == status.HTTP_403_FORBIDDEN

    api_client.force_authenticate(user=user)
    cancelled = api_client.post(f'/activities/{activity.id}/cancel', {}, format='json')
    activity.refresh_from_db()
    assert cancelled.status_code == status.HTTP_200_OK
    assert activity.status == Activity.Status.CANCELLED

    deletable = activity_factory(organizer=user)
    deleted = api_client.delete(f'/activities/{deletable.id}')
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not Activity.objects.filter(id=deletable.id).exists()


def test_recommended_excludes_joined_and_organizer_activities(
    auth_client,
    user,
    activity_factory,
    participation_factory,
):
    own = activity_factory(organizer=user)
    joined = activity_factory(category_id='sport', subcategory_id='football')
    candidate = activity_factory(category_id='sport', subcategory_id='football')
    participation_factory(joined, user, status=Participation.Status.ACCEPTED)

    response = auth_client.get('/activities/recommended?limit=10')
    ids = [item['id'] for item in response.data['items']]

    assert response.status_code == status.HTTP_200_OK
    assert str(candidate.id) in ids
    assert str(joined.id) not in ids
    assert str(own.id) not in ids


def test_saved_activities_crud(auth_client, user, activity_factory):
    activity = activity_factory()

    saved = auth_client.post(f'/me/saved-activities/{activity.id}', {}, format='json')
    assert saved.status_code == status.HTTP_204_NO_CONTENT
    assert SavedActivity.objects.filter(user=user, activity=activity).exists()

    duplicate = auth_client.post(f'/me/saved-activities/{activity.id}', {}, format='json')
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    list_response = auth_client.get('/me/saved-activities')
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.data['items'][0]['id'] == str(activity.id)

    deleted = auth_client.delete(f'/me/saved-activities/{activity.id}')
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not SavedActivity.objects.filter(user=user, activity=activity).exists()


def test_activity_feed_list_filters_and_manual_create(
    auth_client,
    user,
    other_user,
    activity,
    feed_event_factory,
):
    organizer_event = feed_event_factory(user, activity, type='created')
    feed_event_factory(user, activity, type='rated')
    feed_event_factory(other_user, activity, type='joined')

    mine = auth_client.get('/me/activity-feed?category=organizer')
    assert mine.status_code == status.HTTP_200_OK
    assert [item['id'] for item in mine.data['items']] == [str(organizer_event.id)]

    user_feed = auth_client.get(f'/users/{other_user.id}/activity-feed?category=participant')
    assert user_feed.status_code == status.HTTP_200_OK
    assert len(user_feed.data['items']) == 1

    created = auth_client.post(
        '/activity-feed/events',
        {
            'userId': user.id,
            'activityId': activity.id,
            'type': 'missed',
            'metadata': {'source': 'test'},
        },
        format='json',
    )
    assert created.status_code == status.HTTP_201_CREATED
    assert created.data['type'] == 'missed'

    invalid = auth_client.post('/activity-feed/events', {'userId': user.id}, format='json')
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST
