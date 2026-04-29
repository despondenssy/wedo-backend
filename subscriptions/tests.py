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

    me_list = auth_client.get('/me/subscriptions?pinnedOnly=true')
    assert me_list.status_code == status.HTTP_200_OK
    assert [item['userId'] for item in me_list.data['items']] == [str(second.id)]

    sorted_list = auth_client.get('/subscriptions?sort=name')
    assert sorted_list.status_code == status.HTTP_200_OK
    assert [item['user']['name'] for item in sorted_list.data['items']] == ['Alice', 'Bob']

    deleted = auth_client.delete(f'/subscriptions/{target.id}')
    assert deleted.status_code == status.HTTP_200_OK
    assert deleted.data == {'userId': str(target.id), 'deleted': True}
    assert not Subscription.objects.filter(follower=user, target=target).exists()


def test_subscription_detail_404_for_nonexistent_or_not_owned(auth_client, other_user):
    delete_response = auth_client.delete(f'/subscriptions/{other_user.id}')
    patch_response = auth_client.patch(f'/subscriptions/{other_user.id}', {'isPinned': True}, format='json')

    assert delete_response.status_code == status.HTTP_404_NOT_FOUND
    assert patch_response.status_code == status.HTTP_404_NOT_FOUND


def test_subscriptions_endpoint_requires_auth(api_client):
    response = api_client.get('/subscriptions')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
