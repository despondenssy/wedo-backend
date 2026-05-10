from datetime import timedelta, datetime

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from activities.models import Activity, SavedActivity, UserActivityFeedEvent
from participation.models import Participation


pytestmark = pytest.mark.django_db


def test_activity_list_filters_pagination_and_requires_auth(api_client, auth_client, activity_factory):
    football = activity_factory(category_id='sport', subcategory_id='football', location_settlement='Moscow')
    activity_factory(category_id='music', subcategory_id='guitar', location_settlement='Kazan')

    unauth = APIClient().get('/activities')
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    response = auth_client.get('/activities?category_id=sport&city_settlement=Moscow&limit=1')
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['items'][0]['id'] == str(football.id)
    assert body['has_more'] is False
    assert body['next_cursor'] is None


def test_activity_list_text_search_by_title_and_category(auth_client, activity_factory):
    """
    Параметр q ищет вхождение подстроки (без учёта регистра) в названии,
    описании, category_id и subcategory_id. Используется на главном экране
    при вводе поискового запроса.
    """
    yoga = activity_factory(title='Утренняя йога в парке', category_id='sport', subcategory_id='yoga')
    guitar = activity_factory(title='Игра на гитаре', category_id='music', subcategory_id='guitar')
    activity_factory(title='Шахматный турнир', category_id='games', subcategory_id='chess')

    # поиск по части названия — без учёта регистра
    by_title = auth_client.get('/activities?q=ЙОГ')
    ids = [item['id'] for item in by_title.json()['items']]
    assert str(yoga.id) in ids
    assert str(guitar.id) not in ids

    # поиск по category_id
    by_category = auth_client.get('/activities?q=music')
    ids = [item['id'] for item in by_category.json()['items']]
    assert str(guitar.id) in ids
    assert str(yoga.id) not in ids

    # пустой/пробельный q не фильтрует
    blank = auth_client.get('/activities?q=  ')
    assert blank.status_code == status.HTTP_200_OK
    assert len(blank.json()['items']) >= 3


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
    assert detail.json()['policy_flags']['can_edit'] is True

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
    assert UserActivityFeedEvent.objects.filter(user=user, activity=activity, type='cancelled').exists()

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
    body = response.json()
    ids = [item['id'] for item in body['items']]

    assert response.status_code == status.HTTP_200_OK
    assert str(candidate.id) in ids
    assert str(joined.id) not in ids
    assert str(own.id) not in ids


def test_recommended_orders_by_score(
    auth_client,
    user,
    user_factory,
    activity_factory,
    subscription_factory,
):
    """
    Snapshot-тест: фиксирует ожидаемый порядок выдачи рекомендаций
    при известных входах. Если формула или веса поменяются — тест упадёт.

    Сценарий:
    - пользователь с интересом 'football'
    - три активности, отличающиеся ровно одним сигналом:
        A — точное совпадение интереса (subcategory='football') → I=1.0
        B — организатор, на которого подписан → S=1.0
        C — нейтральная, без сигналов
    - все находятся далеко (G=0), без участников (B=0, P=0)

    Скоры по формуле:
        A = 0.33 * 1.0 = 0.33
        B = 0.25 * 1.0 = 0.25
        C = 0.0
    Ожидаем: A → B → C
    """
    user.interests = ['football']
    user.city_settlement = ''
    user.city_region = ''
    user.city_country = ''
    user.city_latitude = 55.75
    user.city_longitude = 37.61
    user.save()

    other_organizer = user_factory()
    followed_organizer = user_factory()
    subscription_factory(follower=user, target=followed_organizer)

    # все активности далеко (география не даёт буст)
    far_lat, far_lng = 10.0, 10.0
    a = activity_factory(
        organizer=other_organizer,
        category_id='sport', subcategory_id='football',
        location_latitude=far_lat, location_longitude=far_lng,
        location_settlement='', location_region='', location_country='',
    )
    b = activity_factory(
        organizer=followed_organizer,
        category_id='music', subcategory_id='guitar',
        location_latitude=far_lat, location_longitude=far_lng,
        location_settlement='', location_region='', location_country='',
    )
    c = activity_factory(
        organizer=other_organizer,
        category_id='music', subcategory_id='guitar',
        location_latitude=far_lat, location_longitude=far_lng,
        location_settlement='', location_region='', location_country='',
    )

    response = auth_client.get('/activities/recommended?limit=10')

    assert response.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in response.json()['items']]
    # все три кандидата в выдаче
    assert {str(a.id), str(b.id), str(c.id)}.issubset(set(ids))
    # фиксируем точный порядок по score: A > B > C
    assert ids.index(str(a.id)) < ids.index(str(b.id)) < ids.index(str(c.id))


def test_recommended_query_count_does_not_scale_with_candidates(
    auth_client,
    user,
    user_factory,
    activity_factory,
    django_assert_max_num_queries,
):
    """
    Регресс-тест на оптимизацию: число SQL-запросов в /activities/recommended
    не должно расти с количеством кандидатов. До оптимизации для 30 кандидатов
    было ~360 запросов (по запросу на каждый сигнал на каждого кандидата).
    После — должно быть около 5-7 (батчами).
    """
    user.interests = ['football']
    user.save()

    organizers = [user_factory() for _ in range(3)]
    for i in range(30):
        activity_factory(
            organizer=organizers[i % 3],
            category_id='sport',
            subcategory_id='football',
        )

    # с запасом ставим 12 — фактическое число должно быть около 5-7.
    # если этот тест упал — значит где-то снова вылез N+1.
    with django_assert_max_num_queries(12):
        response = auth_client.get('/activities/recommended?limit=30')

    assert response.status_code == status.HTTP_200_OK


def test_saved_activities_crud(auth_client, user, activity_factory):
    activity = activity_factory()

    saved = auth_client.post(f'/me/saved-activities/{activity.id}', {}, format='json')
    assert saved.status_code == status.HTTP_204_NO_CONTENT
    assert SavedActivity.objects.filter(user=user, activity=activity).exists()

    duplicate = auth_client.post(f'/me/saved-activities/{activity.id}', {}, format='json')
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST

    list_response = auth_client.get('/me/saved-activities')
    assert list_response.status_code == status.HTTP_200_OK
    assert list_response.json()['items'][0]['id'] == str(activity.id)

    deleted = auth_client.delete(f'/me/saved-activities/{activity.id}')
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    assert not SavedActivity.objects.filter(user=user, activity=activity).exists()


def test_activity_list_sort_and_order(auth_client, activity_factory):
    """sort и order меняют порядок выдачи."""
    a1 = activity_factory(price=100, start_at=timezone.now() + timedelta(days=10))
    a2 = activity_factory(price=50, start_at=timezone.now() + timedelta(days=5))
    a3 = activity_factory(price=200, start_at=timezone.now() + timedelta(days=1))

    # sort=price, order=asc
    resp = auth_client.get('/activities?sort=price&order=asc')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert ids == [str(a2.id), str(a1.id), str(a3.id)]

    # sort=price, order=desc
    resp = auth_client.get('/activities?sort=price&order=desc')
    ids = [item['id'] for item in resp.json()['items']]
    assert ids == [str(a3.id), str(a1.id), str(a2.id)]

    # sort=start_at, order=asc
    resp = auth_client.get('/activities?sort=start_at&order=asc')
    ids = [item['id'] for item in resp.json()['items']]
    assert ids == [str(a3.id), str(a2.id), str(a1.id)]


def test_activity_list_time_filters(auth_client, activity_factory):
    """time_from / time_to фильтруют по времени старта."""
    # активности в разное время
    morning = activity_factory(start_at=timezone.now().replace(hour=9, minute=0))
    afternoon = activity_factory(start_at=timezone.now().replace(hour=14, minute=0))
    evening = activity_factory(start_at=timezone.now().replace(hour=20, minute=0))

    # time_from=10:00 — должны получить afternoon и evening
    resp = auth_client.get('/activities?time_from=10:00')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(morning.id) not in ids
    assert str(afternoon.id) in ids
    assert str(evening.id) in ids

    # time_to=18:00 — должны получить morning и afternoon
    resp = auth_client.get('/activities?time_to=18:00')
    ids = [item['id'] for item in resp.json()['items']]
    assert str(morning.id) in ids
    assert str(afternoon.id) in ids
    assert str(evening.id) not in ids

    # time_from=10:00&time_to=18:00 — только afternoon
    resp = auth_client.get('/activities?time_from=10:00&time_to=18:00')
    ids = [item['id'] for item in resp.json()['items']]
    assert str(morning.id) not in ids
    assert str(afternoon.id) in ids
    assert str(evening.id) not in ids


def test_activity_list_only_available(auth_client, activity_factory, participation_factory, user):
    """only_available=true исключает заполненные активности."""
    # активность без лимита — всегда доступна
    no_limit = activity_factory(pref_max_participants=None)

    # активность с лимитом 2, 1 участник — доступна
    has_spots = activity_factory(pref_max_participants=2)
    participation_factory(has_spots, user, status='accepted')

    # активность с лимитом 1, 1 участник — заполнена
    full = activity_factory(pref_max_participants=1)
    participation_factory(full, user, status='accepted')

    resp = auth_client.get('/activities?only_available=true')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(no_limit.id) in ids
    assert str(has_spots.id) in ids
    assert str(full.id) not in ids


def test_activity_list_max_participants(auth_client, activity_factory):
    """max_participants фильтрует по pref_max_participants."""
    small = activity_factory(pref_max_participants=5)
    medium = activity_factory(pref_max_participants=10)
    large = activity_factory(pref_max_participants=20)

    resp = auth_client.get('/activities?max_participants=10')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(small.id) in ids
    assert str(medium.id) in ids
    assert str(large.id) not in ids


def test_activity_list_timezone_offset_filter(auth_client, activity_factory):
    """time_zone_offset_from/to фильтрует online-активности по часовому поясу."""
    # online-активности в разных таймзонах
    moscow = activity_factory(
        format='online',
        time_zone='Europe/Moscow',
        start_at=timezone.now(),
    )
    london = activity_factory(
        format='online',
        time_zone='Europe/London',
        start_at=timezone.now(),
    )
    ny = activity_factory(
        format='online',
        time_zone='America/New_York',
        start_at=timezone.now(),
    )

    # offline-активность не должна фильтроваться по timezone
    offline = activity_factory(format='offline', time_zone='Europe/Moscow')

    # Фильтр применяется только при format=online в query-параметрах
    # time_zone_offset_from=2 — Moscow (UTC+3) подходит, London (UTC+1) и NY (UTC-4) — нет
    resp = auth_client.get('/activities?format=online&time_zone_offset_from=2')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(moscow.id) in ids
    assert str(london.id) not in ids  # London = UTC+1, 1 < 2
    assert str(ny.id) not in ids  # NY = UTC-4, -4 < 2
    assert str(offline.id) not in ids  # offline не online


def test_activity_list_cursor_pagination_with_sort(auth_client, activity_factory):
    """cursor-пагинация работает с нестандартной сортировкой."""
    a1 = activity_factory(price=100)
    a2 = activity_factory(price=50)
    a3 = activity_factory(price=200)

    # sort=price, order=asc, limit=1
    resp = auth_client.get('/activities?sort=price&order=asc&limit=1')
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert len(body['items']) == 1
    assert body['items'][0]['id'] == str(a2.id)  # price=50
    assert body['has_more'] is True
    assert body['next_cursor'] is not None
    assert ':' in body['next_cursor']  # составной курсор

    # следующая страница
    resp2 = auth_client.get(f'/activities?sort=price&order=asc&limit=1&cursor={body["next_cursor"]}')
    assert resp2.status_code == status.HTTP_200_OK
    body2 = resp2.json()
    assert len(body2['items']) == 1
    assert body2['items'][0]['id'] == str(a1.id)  # price=100


def test_activity_list_timezone_offset_dst_handling(auth_client, activity_factory):
    """Проверка, что offset считается на дату start_at, а не текущую."""
    from datetime import timezone as tz_module

    # активность в London зимой (UTC+0)
    winter = activity_factory(
        format='online',
        time_zone='Europe/London',
        start_at=datetime(2024, 1, 15, 12, 0, tzinfo=tz_module.utc),
    )
    # активность в London летом (UTC+1)
    summer = activity_factory(
        format='online',
        time_zone='Europe/London',
        start_at=datetime(2024, 6, 15, 12, 0, tzinfo=tz_module.utc),
    )

    # фильтр time_zone_offset_from=1 — должна найтись только летняя
    resp = auth_client.get('/activities?format=online&time_zone_offset_from=1')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(summer.id) in ids
    assert str(winter.id) not in ids


def test_activity_list_timezone_offset_fractional(auth_client, activity_factory):
    """Проверка фильтрации по дробным offset'ам (Asia/Kolkata = UTC+5:30)."""
    kolkata = activity_factory(
        format='online',
        time_zone='Asia/Kolkata',
        start_at=timezone.now(),
    )
    moscow = activity_factory(
        format='online',
        time_zone='Europe/Moscow',
        start_at=timezone.now(),
    )

    # time_zone_offset_from=5&time_zone_offset_to=6 — только Kolkata (5.5)
    resp = auth_client.get('/activities?format=online&time_zone_offset_from=5&time_zone_offset_to=6')
    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(kolkata.id) in ids
    assert str(moscow.id) not in ids


def test_activity_create_adds_feed_event(auth_client, user, activity_payload):
    created = auth_client.post('/activities', activity_payload, format='json')

    assert created.status_code == status.HTTP_201_CREATED
    body = created.json()
    assert body['category_id'] == 'sport'
    assert body['preferences']['age_from'] == 18
    assert body['preferences']['max_participants'] == 5
    assert UserActivityFeedEvent.objects.filter(
        user=user,
        activity_id=body['id'],
        type='created',
    ).exists()


def test_activity_list_invalid_cursor_returns_400(auth_client, activity_factory):
    """Невалидный курсор (id — не число) возвращает 400 Bad Request."""
    activity_factory()

    # простой курсор — не число
    resp = auth_client.get('/activities?cursor=invalid')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert 'Invalid cursor format' in resp.json()['detail']

    # составной курсор — id не число
    resp = auth_client.get('/activities?cursor=10:xyz')
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_activity_feed_list_filters(
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
    assert [item['id'] for item in mine.json()['items']] == [str(organizer_event.id)]

    user_feed = auth_client.get(f'/users/{other_user.id}/activity-feed?category=participant')
    assert user_feed.status_code == status.HTTP_200_OK
    assert len(user_feed.json()['items']) == 1
