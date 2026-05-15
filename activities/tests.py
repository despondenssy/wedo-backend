from datetime import UTC, timedelta, datetime

import pytest
from django.utils import timezone
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

    deletable = activity_factory(organizer=user)
    deleted = api_client.delete(f'/activities/{deletable.id}')
    deletable.refresh_from_db()
    assert deleted.status_code == status.HTTP_204_NO_CONTENT
    # Активную активность не сносим физически — переводим в cancelled,
    # чтобы старые уведомления и история не вели в никуда.
    assert deletable.status == Activity.Status.CANCELLED
    assert deletable.cancelled_at is not None


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


def test_activity_list_time_filters_build_connected_utc_windows(auth_client, activity_factory):
    """date_from/date_to/time_from/time_to are connected UTC datetime windows."""
    false_positive = activity_factory(
        start_at=datetime(2026, 5, 19, 15, 0, tzinfo=UTC),
        time_zone='Europe/Moscow',
    )
    matching = activity_factory(
        start_at=datetime(2026, 5, 19, 22, 0, tzinfo=UTC),
        time_zone='Europe/Moscow',
    )

    resp = auth_client.get(
        '/activities?date_from=2026-05-19&date_to=2026-05-24'
        '&time_from=21:30&time_to=20:30'
    )

    assert resp.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in resp.json()['items']]
    assert str(false_positive.id) not in ids
    assert str(matching.id) in ids


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


def test_activity_list_cursor_pagination_with_sort(auth_client, activity_factory):
    """cursor-пагинация работает с нестандартной сортировкой."""
    from urllib.parse import quote
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
    assert '_' in body['next_cursor']  # составной курсор

    # следующая страница
    resp2 = auth_client.get(f'/activities?sort=price&order=asc&limit=1&cursor={quote(body["next_cursor"])}')
    assert resp2.status_code == status.HTTP_200_OK
    body2 = resp2.json()
    assert len(body2['items']) == 1
    assert body2['items'][0]['id'] == str(a1.id)  # price=100


def test_activity_create_persists_payload(auth_client, user, activity_payload):
    created = auth_client.post('/activities', activity_payload, format='json')

    assert created.status_code == status.HTTP_201_CREATED
    body = created.json()
    assert body['category_id'] == 'sport'
    assert body['preferences']['age_from'] == 18
    assert body['preferences']['max_participants'] == 5


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


def test_policy_flags_for_organizer_before_start(auth_client, user, activity_factory):
    """Организатор до начала активности: can_edit=True, can_cancel_activity=True."""
    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_edit'] is True
    assert flags['can_cancel_activity'] is True
    assert flags['can_join'] is False
    assert flags['can_leave'] is False
    assert flags['can_cancel_request'] is False
    assert flags['can_manage_requests'] is True
    assert flags['can_rate'] is False


def test_policy_flags_for_organizer_after_start(auth_client, user, activity_factory):
    """Организатор после начала активности: can_edit=False, can_cancel_activity=False."""
    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() - timedelta(hours=1),
        end_at=timezone.now() + timedelta(hours=1),
    )
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_edit'] is False
    assert flags['can_cancel_activity'] is False
    assert flags['can_manage_requests'] is True  # ещё не закончилась
    assert flags['can_join'] is False


def test_policy_flags_for_organizer_after_end(auth_client, user, activity_factory):
    """Организатор после окончания активности: все флаги False."""
    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() - timedelta(hours=3),
        end_at=timezone.now() - timedelta(hours=1),
    )
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert all(not v for v in flags.values()), f'Expected all False, got {flags}'


def test_policy_flags_for_participant_accepted(auth_client, user, activity_factory, participation_factory):
    """Участник (accepted) до окончания: can_leave=True, can_join=False."""
    activity = activity_factory(
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    participation_factory(activity, user, status='accepted')

    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_leave'] is True
    assert flags['can_join'] is False
    assert flags['can_cancel_request'] is False
    assert flags['can_rate'] is False


def test_policy_flags_for_participant_attended_without_rating(
    auth_client, user, activity_factory, participation_factory,
):
    """Участник (attended) без оценки: can_rate=True."""
    activity = activity_factory(
        start_at=timezone.now() - timedelta(hours=3),
        end_at=timezone.now() - timedelta(hours=1),
    )
    participation_factory(activity, user, status='attended')

    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_rate'] is True
    assert flags['can_leave'] is False  # attended не может выйти


def test_policy_flags_for_participant_attended_with_rating(
    auth_client, user, activity_factory, participation_factory, rating_factory,
):
    """Участник (attended) с оценкой: can_rate=False."""
    activity = activity_factory(
        start_at=timezone.now() - timedelta(hours=3),
        end_at=timezone.now() - timedelta(hours=1),
    )
    participation_factory(activity, user, status='attended')
    rating_factory(activity, user, rating=5)

    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_rate'] is False


def test_policy_flags_for_pending_participant(auth_client, user, activity_factory, participation_factory):
    """Участник с pending-заявкой: can_cancel_request=True."""
    activity = activity_factory(
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    participation_factory(activity, user, status='pending')

    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_cancel_request'] is True
    assert flags['can_join'] is False
    assert flags['can_leave'] is False


def test_policy_flags_for_cancelled_activity(auth_client, user, activity_factory):
    """Отменённая активность: все флаги False."""
    activity = activity_factory(
        organizer=user,
        status=Activity.Status.CANCELLED,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert all(not v for v in flags.values()), f'Expected all False, got {flags}'


def test_policy_flags_for_full_activity(auth_client, user, activity_factory, participation_factory):
    """Заполненная активность: can_join=False."""
    activity = activity_factory(
        pref_max_participants=1,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    # организатор считается участником, поэтому pref_max_participants=1 уже заполнено
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_join'] is False


def test_policy_flags_for_other_user_can_join(auth_client, user, activity_factory):
    """Другой пользователь может вступить в активную активность."""
    activity = activity_factory(
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    detail = auth_client.get(f'/activities/{activity.id}')
    flags = detail.json()['policy_flags']

    assert flags['can_join'] is True
    assert flags['can_leave'] is False
    assert flags['can_cancel_request'] is False
    assert flags['can_manage_requests'] is False
    assert flags['can_rate'] is False
    assert flags['can_edit'] is False
    assert flags['can_cancel_activity'] is False


# ===== KudaGo integration tests =====


def test_kudago_activity_serializer_source_field(auth_client, activity_factory):
    """Проверяем, что source в JSON возвращается как 'KudaGo' для kudago-событий."""
    activity = activity_factory(
        source=Activity.Source.KUDAGO,
        kudago_id=100500,
        kudago_url='https://kudago.com/msk/event/test/',
        organizer=None,
    )
    response = auth_client.get(f'/activities/{activity.id}')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['source'] == 'KudaGo'
    assert data['kudago_url'] == 'https://kudago.com/msk/event/test/'


def test_kudago_activity_serializer_source_user(auth_client, activity_factory):
    """Проверяем, что для обычных событий source = 'User'."""
    activity = activity_factory(source=Activity.Source.USER)
    response = auth_client.get(f'/activities/{activity.id}')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['source'] == 'User'


def test_kudago_activity_organizer_nullable(auth_client, activity_factory):
    """Проверяем, что organizer может быть null для KudaGo-события."""
    activity = activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100501,
    )
    response = auth_client.get(f'/activities/{activity.id}')
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data['organizer'] is None


def test_kudago_activity_can_become_organizer_flag(auth_client, activity_factory):
    """Проверяем policy_flags для KudaGo-события без организатора."""
    activity = activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100502,
    )
    response = auth_client.get(f'/activities/{activity.id}')
    assert response.status_code == status.HTTP_200_OK
    flags = response.json()['policy_flags']
    assert flags['can_become_organizer'] is True
    assert flags['can_join'] is False  # без организатора нельзя присоединиться


def test_kudago_activity_can_become_organizer_false_when_has_organizer(auth_client, activity_factory, user_factory):
    """Проверяем, что can_become_organizer=False, если у KudaGo-события уже есть организатор."""
    organizer = user_factory()
    activity = activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=organizer,
        kudago_id=100503,
    )
    response = auth_client.get(f'/activities/{activity.id}')
    assert response.status_code == status.HTTP_200_OK
    flags = response.json()['policy_flags']
    assert flags['can_become_organizer'] is False


def test_cleanup_kudago_command_deletes_expired(auth_client, activity_factory):
    """Проверяем, что management command cleanup_kudago удаляет все устаревшие KudaGo-события."""
    from django.core.management import call_command

    # Создаём устаревшее KudaGo-событие (закончилось)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100507,
        end_at=timezone.now() - timedelta(days=1),
    )
    # Создаём активное KudaGo-событие (не должно удалиться)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100508,
        end_at=timezone.now() + timedelta(days=1),
    )

    call_command('cleanup_kudago')

    remaining = Activity.objects.filter(source=Activity.Source.KUDAGO).count()
    assert remaining == 1  # только активное


def test_cleanup_kudago_dry_run_does_not_delete(auth_client, activity_factory):
    """Проверяем, что dry-run не удаляет события."""
    from django.core.management import call_command

    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100510,
        end_at=timezone.now() - timedelta(days=1),
    )

    call_command('cleanup_kudago', '--dry-run')

    remaining = Activity.objects.filter(source=Activity.Source.KUDAGO).count()
    assert remaining == 1


def test_kudago_activity_list_item_has_source(auth_client, activity_factory):
    """Проверяем, что в списке активностей тоже приходит source."""
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100511,
    )
    activity_factory(source=Activity.Source.USER)

    response = auth_client.get('/activities')
    assert response.status_code == status.HTTP_200_OK
    items = response.json()['items']
    sources = {item['source'] for item in items}
    assert 'KudaGo' in sources
    assert 'User' in sources


def test_kudago_map_event_to_activity_multi_date(activity_factory):
    """Проверяем _map_event_to_activity: мульти-дейт, фильтрация по окну, requires_approval, is_free, crafts→painting."""
    from activities.management.commands.import_kudago import _map_event_to_activity

    now_ts = int(datetime.now(UTC).timestamp())
    day = 86400

    event: dict = {
        "id": 999001,
        "title": "Мастер-класс по рисованию",
        "short_title": "Рисование",
        "description": "Научимся рисовать акварелью",
        "tagline": "Творческий вечер",
        "body_text": "",
        "site_url": "https://kudago.ru/event/999001",
        "categories": ["creative"],
        "location": {"slug": "msk", "name": "Москва"},
        "place": {
            "title": "Арт-студия",
            "coords": {"lat": 55.75, "lon": 37.61},
            "address": "ул. Тверская, 1",
        },
        "dates": [
            {"start": now_ts + day, "end": now_ts + day + 7200},
            {"start": now_ts + 2 * day, "end": now_ts + 2 * day + 7200},
            {"start": now_ts + 3 * day, "end": now_ts + 3 * day + 7200},
        ],
        "images": [],
        "is_free": True,
        "age_restriction": "12+",
        "price": "",
    }

    actual_since = now_ts
    actual_until = now_ts + 3 * day  # третья дата на границе — попадает

    activities = _map_event_to_activity(event, "msk", actual_since, actual_until)

    # Должно быть 3 Activity (все даты в окне)
    assert len(activities) == 3, f"Expected 3 activities, got {len(activities)}"

    # Все имеют одинаковый kudago_id (оригинальный event["id"])
    for ad in activities:
        assert ad["kudago_id"] == 999001

    # Все имеют разные start_at
    start_ats = [ad["start_at"] for ad in activities]
    assert len(set(start_ats)) == 3

    # requires_approval=False
    for ad in activities:
        assert ad["requires_approval"] is False

    # is_free → price=0
    for ad in activities:
        assert ad["price"] == 0.0

    # category/subcategory
    for ad in activities:
        assert ad["category_id"] == "creative"
        # description содержит "акварел" → subcategory должна быть "painting"
        assert ad["subcategory_id"] == "painting"

    # description: body_text пустой, description есть → берётся description
    for ad in activities:
        assert "акварелью" in ad["description"]


def test_kudago_map_event_to_activity_description_with_tagline(activity_factory):
    """Если нет body_text и description, но есть tagline — description = 'title · tagline'."""
    from activities.management.commands.import_kudago import _map_event_to_activity

    now_ts = int(datetime.now(UTC).timestamp())
    day = 86400

    event: dict = {
        "id": 999002,
        "title": "Концерт",
        "short_title": "",
        "description": "",
        "body_text": "",
        "tagline": "Лучшие хиты",
        "site_url": "https://kudago.ru/event/999002",
        "categories": ["concert"],
        "location": {"slug": "msk", "name": "Москва"},
        "place": {
            "title": "Клуб",
            "coords": {"lat": 55.75, "lon": 37.61},
            "address": "ул. Арбат, 10",
        },
        "dates": [
            {"start": now_ts + day, "end": now_ts + day + 7200},
        ],
        "images": [],
        "is_free": False,
        "age_restriction": "",
        "price": "1000",
    }

    activities = _map_event_to_activity(event, "msk", now_ts, now_ts + 2 * day)
    assert len(activities) == 1
    assert activities[0]["description"] == "Концерт · Лучшие хиты"


def test_kudago_map_event_to_activity_filters_dates_outside_window(activity_factory):
    """Даты вне окна actual_since..actual_until отфильтровываются."""
    from activities.management.commands.import_kudago import _map_event_to_activity

    now_ts = int(datetime.now(UTC).timestamp())
    day = 86400

    event: dict = {
        "id": 999003,
        "title": "Фестиваль",
        "description": "Большой фестиваль",
        "site_url": "https://kudago.ru/event/999003",
        "categories": ["concert"],
        "location": {"slug": "msk", "name": "Москва"},
        "place": {
            "title": "Парк",
            "coords": {"lat": 55.75, "lon": 37.61},
            "address": "Парк Горького",
        },
        "dates": [
            {"start": now_ts - 10 * day},   # прошлое — мимо
            {"start": now_ts + day},          # в окне
            {"start": now_ts + 5 * day},      # в окне
            {"start": now_ts + 20 * day},     # будущее — мимо
        ],
        "images": [],
        "is_free": False,
        "age_restriction": "",
        "price": "",
    }

    actual_since = now_ts
    actual_until = now_ts + 10 * day

    activities = _map_event_to_activity(event, "msk", actual_since, actual_until)
    assert len(activities) == 2


def test_kudago_map_event_to_activity_returns_empty_for_no_coords(activity_factory):
    """Если нет координат — time_zone=None → возвращаем пустой список."""
    from activities.management.commands.import_kudago import _map_event_to_activity

    now_ts = int(datetime.now(UTC).timestamp())
    day = 86400

    event: dict = {
        "id": 999004,
        "title": "Событие без координат",
        "description": "Где-то далеко",
        "site_url": "https://kudago.ru/event/999004",
        "categories": ["concert"],
        "location": {"slug": "msk", "name": "Москва"},
        "place": {
            "title": "Неизвестное место",
            "coords": {},
            "address": "",
        },
        "dates": [
            {"start": now_ts + day},
        ],
        "images": [],
        "is_free": False,
        "age_restriction": "",
        "price": "",
    }

    activities = _map_event_to_activity(event, "msk", now_ts, now_ts + 2 * day)
    assert activities == []


# ===== Source filter and sorting tests =====


def test_activity_list_filter_by_source_user(auth_client, activity_factory):
    """GET /activities?source=user возвращает только user-события."""
    activity_factory(source=Activity.Source.USER)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100601,
    )

    response = auth_client.get('/activities?source=user')
    assert response.status_code == status.HTTP_200_OK
    items = response.json()['items']
    assert all(item['source'] == 'User' for item in items)


def test_activity_list_filter_by_source_kudago(auth_client, activity_factory):
    """GET /activities?source=kudago возвращает только kudago-события."""
    activity_factory(source=Activity.Source.USER)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100602,
    )

    response = auth_client.get('/activities?source=kudago')
    assert response.status_code == status.HTTP_200_OK
    items = response.json()['items']
    assert all(item['source'] == 'KudaGo' for item in items)


def test_activity_list_sorts_kudago_last(auth_client, activity_factory):
    """Без фильтра source kudago-события в конце списка."""
    activity_factory(source=Activity.Source.USER)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100603,
    )

    response = auth_client.get('/activities')
    assert response.status_code == status.HTTP_200_OK
    items = response.json()['items']
    # Все User должны быть перед KudaGo
    user_ids = [i['id'] for i in items if i['source'] == 'User']
    kudago_ids = [i['id'] for i in items if i['source'] == 'KudaGo']
    if user_ids and kudago_ids:
        last_user_idx = max(items.index(u) for u in items if u['source'] == 'User')
        first_kudago_idx = min(items.index(k) for k in items if k['source'] == 'KudaGo')
        assert last_user_idx < first_kudago_idx


def test_activity_list_source_filter_with_sort(auth_client, activity_factory):
    """Фильтр source + сортировка работают вместе."""
    activity_factory(source=Activity.Source.USER, price=100)
    activity_factory(source=Activity.Source.USER, price=50)
    activity_factory(
        source=Activity.Source.KUDAGO,
        organizer=None,
        kudago_id=100604,
        price=200,
    )

    # source=user + sort=price, order=asc
    response = auth_client.get('/activities?source=user&sort=price&order=asc')
    assert response.status_code == status.HTTP_200_OK
    items = response.json()['items']
    assert len(items) == 2
    assert all(item['source'] == 'User' for item in items)
    prices = [item['price'] for item in items]
    assert prices == sorted(prices)


def test_activity_list_cursor_pagination_with_source_sort(auth_client, activity_factory):
    """Курсорная пагинация работает с source_order (kudago в конце)."""
    from urllib.parse import urlencode
    # Создаём 3 user и 2 kudago
    for i in range(3):
        activity_factory(source=Activity.Source.USER)
    for i in range(2):
        activity_factory(
            source=Activity.Source.KUDAGO,
            organizer=None,
            kudago_id=100610 + i,
        )

    # Первая страница: limit=3, должны получить 3 user-события
    resp1 = auth_client.get('/activities?limit=3')
    assert resp1.status_code == status.HTTP_200_OK
    body1 = resp1.json()
    assert len(body1['items']) == 3
    assert all(item['source'] == 'User' for item in body1['items'])
    assert body1['has_more'] is True
    assert body1['next_cursor'] is not None
    # Курсор должен быть составным (3 части)
    assert len(body1['next_cursor'].split('_')) == 3

    # Вторая страница: должны получить оставшиеся kudago-события
    params = urlencode({'limit': 3, 'cursor': body1['next_cursor']})
    resp2 = auth_client.get(f'/activities?{params}')
    assert resp2.status_code == status.HTTP_200_OK
    body2 = resp2.json()
    assert len(body2['items']) == 2
    assert all(item['source'] == 'KudaGo' for item in body2['items'])
    assert body2['has_more'] is False


def test_kudago_map_event_to_activity_returns_empty_for_no_site_url(activity_factory):
    """Если нет site_url — возвращаем пустой список."""
    from activities.management.commands.import_kudago import _map_event_to_activity

    now_ts = int(datetime.now(UTC).timestamp())
    day = 86400

    event: dict = {
        "id": 999005,
        "title": "Событие без ссылки",
        "description": "Описание",
        "site_url": "",
        "categories": ["concert"],
        "location": {"slug": "msk", "name": "Москва"},
        "place": {
            "title": "Место",
            "coords": {"lat": 55.75, "lon": 37.61},
            "address": "Адрес",
        },
        "dates": [
            {"start": now_ts + day},
        ],
        "images": [],
        "is_free": False,
        "age_restriction": "",
        "price": "",
    }

    activities = _map_event_to_activity(event, "msk", now_ts, now_ts + 2 * day)
    assert activities == []
