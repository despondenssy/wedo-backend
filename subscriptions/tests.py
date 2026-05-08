import pytest
from rest_framework import status

from subscriptions.models import Subscription


pytestmark = pytest.mark.django_db


def test_subscription_list_and_delete(
    auth_client,
    user,
    user_factory,
):
    target = user_factory(name='Alice')
    second = user_factory(name='Bob')

    Subscription.objects.create(follower=user, target=target)
    Subscription.objects.create(follower=user, target=second, is_pinned=True)

    me_list = auth_client.get('/me/subscriptions?pinned_only=true')
    assert me_list.status_code == status.HTTP_200_OK
    assert [item['user_id'] for item in me_list.json()['items']] == [str(second.id)]

    sorted_list = auth_client.get('/subscriptions?sort=name')
    assert sorted_list.status_code == status.HTTP_200_OK
    assert [item['user']['name'] for item in sorted_list.json()['items']] == ['Alice', 'Bob']

    deleted = auth_client.delete(f'/subscriptions/{target.id}')
    assert deleted.status_code == status.HTTP_200_OK
    assert deleted.json() == {'user_id': str(target.id), 'deleted': True}
    assert not Subscription.objects.filter(follower=user, target=target).exists()


def test_subscription_detail_404_for_nonexistent_or_not_owned(auth_client, other_user):
    delete_response = auth_client.delete(f'/subscriptions/{other_user.id}')
    patch_response = auth_client.patch(f'/subscriptions/{other_user.id}', {'is_pinned': True}, format='json')

    assert delete_response.status_code == status.HTTP_404_NOT_FOUND
    assert patch_response.status_code == status.HTTP_404_NOT_FOUND


def test_subscription_create(auth_client, user_factory):
    target = user_factory()

    created = auth_client.post('/subscriptions', {'user_id': target.id}, format='json')
    assert created.status_code == status.HTTP_201_CREATED
    assert created.json()['user_id'] == str(target.id)

    patched = auth_client.patch(f'/subscriptions/{target.id}', {'is_pinned': True}, format='json')
    subscription = Subscription.objects.get(target=target)

    assert patched.status_code == status.HTTP_200_OK
    assert patched.json()['is_pinned'] is True
    assert subscription.is_pinned is True


def test_subscriptions_endpoint_requires_auth(api_client):
    response = api_client.get('/subscriptions')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
