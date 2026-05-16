from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from activities.models import Activity
from participation.models import Participation
from users.models import QrToken, User


pytestmark = pytest.mark.django_db


def register_payload(email='new@example.com'):
    return {
        'name': 'New User',
        'email': email,
        'password': 'StrongPass123',
        'birth_date': '1998-05-20',
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
        'show_birth_date': True,
    }


def test_register_login_refresh_and_logout(api_client, user_factory):
    response = api_client.post('/auth/register', register_payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body['user']['show_birth_date'] is True
    assert body['user']['social_link'] is None
    assert body['user']['about_me'] is None
    assert body['tokens']['access_token']
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
    assert login_body['tokens']['refresh_token']

    refresh = api_client.post(
        '/auth/refresh',
        {'refresh_token': login_body['tokens']['refresh_token']},
        format='json',
    )
    assert refresh.status_code == status.HTTP_200_OK
    assert refresh.json()['access_token']

    api_client.force_authenticate(user=user)
    logout = api_client.post(
        '/auth/logout',
        {'refresh_token': login_body['tokens']['refresh_token']},
        format='json',
    )
    assert logout.status_code == status.HTTP_204_NO_CONTENT


def test_refresh_rotates_and_blacklists_old_token(api_client, user):
    """
    /auth/refresh реализует ротацию: возвращает НОВЫЙ refresh-токен,
    старый помещается в blacklist. Повторная попытка использовать
    старый токен возвращает 401.
    """
    login = api_client.post(
        '/auth/login',
        {'email': user.email, 'password': 'StrongPass123'},
        format='json',
    )
    assert login.status_code == status.HTTP_200_OK
    old_refresh = login.json()['tokens']['refresh_token']

    first_refresh = api_client.post(
        '/auth/refresh', {'refresh_token': old_refresh}, format='json',
    )
    assert first_refresh.status_code == status.HTTP_200_OK
    new_refresh = first_refresh.json()['refresh_token']
    # ротация: новый токен — это другой токен
    assert new_refresh != old_refresh

    # попытка повторно использовать СТАРЫЙ токен — теперь в blacklist'е
    replay = api_client.post(
        '/auth/refresh', {'refresh_token': old_refresh}, format='json',
    )
    assert replay.status_code == status.HTTP_401_UNAUTHORIZED


def test_refresh_chain_each_step_invalidates_previous(api_client, user):
    """Цепочка ротаций: после второго refresh первый новый тоже инвалидирован."""
    login = api_client.post(
        '/auth/login',
        {'email': user.email, 'password': 'StrongPass123'},
        format='json',
    )
    refresh_1 = login.json()['tokens']['refresh_token']

    response_2 = api_client.post(
        '/auth/refresh', {'refresh_token': refresh_1}, format='json',
    )
    refresh_2 = response_2.json()['refresh_token']

    response_3 = api_client.post(
        '/auth/refresh', {'refresh_token': refresh_2}, format='json',
    )
    assert response_3.status_code == status.HTTP_200_OK
    refresh_3 = response_3.json()['refresh_token']

    # refresh_2 после использования тоже в blacklist
    replay = api_client.post(
        '/auth/refresh', {'refresh_token': refresh_2}, format='json',
    )
    assert replay.status_code == status.HTTP_401_UNAUTHORIZED
    # refresh_3 ещё рабочий
    assert refresh_3 != refresh_2


def test_register_requires_show_birth_date(api_client):
    payload = register_payload()
    payload.pop('show_birth_date')

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'show_birth_date' in response.json()


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


def test_register_without_city_region(api_client):
    """Регистрация должна проходить без поля region в city (кейс Москвы/Питера)."""
    payload = register_payload()
    payload['city'].pop('region')

    response = api_client.post('/auth/register', payload, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body['user']['city']['region'] is None


def test_me_returns_birth_date_for_owner(auth_client, user):
    """GET /me должен возвращать birth_date для владельца аккаунта."""
    response = auth_client.get('/me')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['is_current_user'] is True
    assert 'birth_date' in body
    assert body['birth_date'] is not None


def test_user_profile_hides_birth_date_for_others(api_client, user, other_user):
    """GET /users/{id} не должен возвращать birth_date для чужих профилей."""
    api_client.force_authenticate(user=other_user)
    response = api_client.get(f'/users/{user.id}')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['is_current_user'] is False
    assert 'birth_date' in body
    assert body['birth_date'] is None


def test_login_and_refresh_reject_invalid_data(api_client, user):
    bad_login = api_client.post(
        '/auth/login',
        {'email': user.email, 'password': 'wrong'},
        format='json',
    )
    assert bad_login.status_code == status.HTTP_401_UNAUTHORIZED

    no_refresh = api_client.post('/auth/refresh', {}, format='json')
    assert no_refresh.status_code == status.HTTP_400_BAD_REQUEST

    bad_refresh = api_client.post('/auth/refresh', {'refresh_token': 'bad'}, format='json')
    assert bad_refresh.status_code == status.HTTP_401_UNAUTHORIZED


def test_me_get_patch_show_birth_date_and_delete(auth_client, user):
    get_response = auth_client.get('/me')
    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json()['is_current_user'] is True

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
            'show_birth_date': True,
            'social_link': 'https://t.me/testuser',
            'about_me': 'Люблю спорт и путешествия',
        },
        format='json',
    )
    user.refresh_from_db()
    assert patch_response.status_code == status.HTTP_200_OK
    assert user.name == 'Updated'
    assert user.city_settlement == 'Saint Petersburg'
    assert user.show_birth_date is True
    assert user.social_link == 'https://t.me/testuser'
    assert user.about_me == 'Люблю спорт и путешествия'
    assert patch_response.json()['show_birth_date'] is True
    assert patch_response.json()['social_link'] == 'https://t.me/testuser'
    assert patch_response.json()['about_me'] == 'Люблю спорт и путешествия'

    delete_response = auth_client.delete('/me')
    user.refresh_from_db()
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    assert user.is_active is False
    assert user.deleted_at is not None
    # персональные данные анонимизированы — реальное имя и email
    # не остаются в системе после удаления аккаунта
    assert user.name == 'Удалённый аккаунт'
    assert user.email == f'deleted-{user.id}@deleted.local'
    assert user.city_settlement is None
    assert user.interests == []
    assert user.social_link is None
    assert user.about_me is None




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


def test_user_history_event_log_tabs(
    auth_client,
    user,
    activity_factory,
    participation_factory,
    rating_factory,
):
    """
    Новые табы /history?tab=organizer|participant|ratings|all возвращают
    ленту событий пользователя (organized/joined/attended/rated/...).
    На одну активность может приходиться несколько событий.
    """
    # организовал
    organized = activity_factory(organizer=user)

    # организовал и потом отменил — два события
    org_and_cancel = activity_factory(
        organizer=user,
        status=Activity.Status.CANCELLED,
        cancelled_at=timezone.now(),
    )

    # участвовал — посетил — оценил: три события на одну активность
    full_cycle = activity_factory()
    participation_factory(full_cycle, user, status=Participation.Status.ATTENDED)
    rating_factory(full_cycle, user, rating=5, comment='Класс')

    # шум
    activity_factory()  # чужая
    pending_only = activity_factory()
    participation_factory(pending_only, user, status=Participation.Status.PENDING)

    def events_for(tab):
        r = auth_client.get(f'/users/{user.id}/history?tab={tab}')
        assert r.status_code == status.HTTP_200_OK, r.json()
        return r.json()['items']

    # organizer — два события про organized + одно cancelled
    organizer_events = events_for('organizer')
    organizer_types = sorted(e['type'] for e in organizer_events)
    assert organizer_types == ['cancelled', 'organized', 'organized']

    # participant — joined и attended на full_cycle
    participant_events = events_for('participant')
    participant_types = sorted(e['type'] for e in participant_events)
    assert participant_types == ['attended', 'joined']

    # ratings — одно событие про оценку, с рейтингом и комментом
    rating_events = events_for('ratings')
    assert len(rating_events) == 1
    r0 = rating_events[0]
    assert r0['type'] == 'rated'
    assert r0['rating'] == 5
    assert r0['rating_comment'] == 'Класс'

    # каждое событие содержит полную карточку активности
    assert 'activity' in r0
    assert r0['activity']['id'] == str(full_cycle.id)

    # all — объединение всех событий, отсортированных по occurred_at desc
    all_events = events_for('all')
    assert len(all_events) == 6  # 2 organized + 1 cancelled + 1 joined + 1 attended + 1 rated
    # сортировка по времени, новые сверху
    timestamps = [e['occurred_at'] for e in all_events]
    assert timestamps == sorted(timestamps, reverse=True)

    # pending в ленте не появляется
    all_activity_ids = {e['activity']['id'] for e in all_events}
    assert str(pending_only.id) not in all_activity_ids


def test_my_activities_filters_apply_to_old_tabs(
    auth_client,
    user,
    activity_factory,
):
    """
    /me/my-activities принимает тот же набор фильтров что и /activities
    (q, category_id, format и т.д.). Действует на старых табах
    created/upcoming/attended/future_created.
    """
    activity_factory(organizer=user, title='Моя йога', category_id='sport', subcategory_id='yoga')
    activity_factory(organizer=user, title='Мой концерт', category_id='music', subcategory_id='guitar')

    response = auth_client.get('/me/my-activities?tab=created&q=йога')
    assert response.status_code == status.HTTP_200_OK
    titles = [item['title'] for item in response.json()['items']]
    assert 'Моя йога' in titles
    assert 'Мой концерт' not in titles

    by_category = auth_client.get('/me/my-activities?tab=created&category_id=music')
    titles = [item['title'] for item in by_category.json()['items']]
    assert 'Мой концерт' in titles
    assert 'Моя йога' not in titles


def test_my_activities_filters_apply_to_event_tabs(
    auth_client,
    user,
    activity_factory,
    participation_factory,
    rating_factory,
):
    """
    /me/my-activities на новых event-табах (all/organizer/participant/ratings)
    тоже принимает фильтры — событие появляется только если активность
    прошла фильтр.
    """
    sport = activity_factory(organizer=user, category_id='sport', subcategory_id='yoga', title='Йога')
    music = activity_factory(category_id='music', subcategory_id='guitar', title='Гитара')
    participation_factory(music, user, status=Participation.Status.ATTENDED)
    rating_factory(music, user, rating=5)

    response = auth_client.get('/me/my-activities?tab=all&category_id=music')
    assert response.status_code == status.HTTP_200_OK
    activity_ids = {e['activity']['id'] for e in response.json()['items']}
    assert str(sport.id) not in activity_ids
    assert str(music.id) in activity_ids
    types = [e['type'] for e in response.json()['items']]
    assert 'rated' in types


def test_user_history_does_not_apply_filters(
    auth_client,
    user,
    activity_factory,
):
    """
    /users/<id>/history — публичный endpoint, фильтры игнорируются даже
    если в URL переданы. Поведение симметричное — что для своей истории,
    что для чужой.
    """
    activity_factory(organizer=user, title='Йога', category_id='sport')
    activity_factory(organizer=user, title='Гитара', category_id='music')

    # передаём q — но фильтр должен быть проигнорирован, видим обе активности
    response = auth_client.get(f'/users/{user.id}/history?tab=created&q=йога')
    assert response.status_code == status.HTTP_200_OK
    titles = [item['title'] for item in response.json()['items']]
    assert 'Йога' in titles
    assert 'Гитара' in titles


def test_user_history_future_created_tab(
    auth_client,
    user,
    activity_factory,
):
    """
    Таб future_created — для экрана QR-сканирования организатора.
    Возвращает активные активности юзера, которые ещё не закончились
    (end_at >= now). Прошедшие, отменённые и активности других —
    не должны попадать.
    """
    from datetime import timedelta
    from django.utils import timezone

    now = timezone.now()
    future_active = activity_factory(
        organizer=user,
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=1, hours=2),
    )
    # активность идёт прямо сейчас — должна попадать в ответ
    ongoing = activity_factory(
        organizer=user,
        start_at=now - timedelta(hours=1),
        end_at=now + timedelta(hours=1),
    )
    past = activity_factory(
        organizer=user,
        start_at=now - timedelta(days=2),
        end_at=now - timedelta(days=2, hours=-2),
    )
    cancelled = activity_factory(
        organizer=user,
        start_at=now + timedelta(days=3),
        end_at=now + timedelta(days=3, hours=2),
        status=Activity.Status.CANCELLED,
    )
    other_user_activity = activity_factory()  # организует не наш пользователь

    response = auth_client.get(f'/users/{user.id}/history?tab=future_created')
    assert response.status_code == status.HTTP_200_OK
    ids = [item['id'] for item in response.json()['items']]

    assert str(future_active.id) in ids
    assert str(ongoing.id) in ids       # текущая активность тоже должна быть
    assert str(past.id) not in ids
    assert str(cancelled.id) not in ids
    assert str(other_user_activity.id) not in ids


def test_organizer_deletion_transfers_activity_to_first_participant(
    auth_client,
    user,
    user_factory,
    activity_factory,
    participation_factory,
):
    """
    При удалении организатора активность не отменяется, если есть участники —
    она передаётся первому по дате присоединения. Новый организатор получает
    уведомление, его участие удаляется (он теперь организатор, не участник).
    Прошлые активности не трогаются.
    """
    from datetime import timedelta
    from django.utils import timezone
    from notifications.models import Notification

    now = timezone.now()
    future = activity_factory(
        organizer=user,
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=1, hours=2),
    )
    past = activity_factory(
        organizer=user,
        start_at=now - timedelta(days=5),
        end_at=now - timedelta(days=5, hours=-2),
    )

    # порядок присоединения важен: first_participant получит организаторство
    first_participant = user_factory()
    later_participant = user_factory()
    p1 = participation_factory(future, first_participant, status=Participation.Status.ACCEPTED)
    p2 = participation_factory(future, later_participant, status=Participation.Status.ACCEPTED)
    # вручную раздвинем created_at чтобы порядок был детерминированный
    p1.created_at = now - timedelta(hours=2)
    p1.save(update_fields=['created_at'])
    p2.created_at = now - timedelta(hours=1)
    p2.save(update_fields=['created_at'])

    delete_response = auth_client.delete('/me')
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT

    future.refresh_from_db()
    past.refresh_from_db()

    # активность не отменена, у неё новый организатор
    assert future.status == Activity.Status.ACTIVE
    assert future.organizer_id == first_participant.id

    # участие нового организатора удалено
    assert not Participation.objects.filter(activity=future, user=first_participant).exists()

    # уведомление пришло именно ему — теперь это типизированное ORGANIZER_ASSIGNED
    assert Notification.objects.filter(
        user=first_participant,
        type=Notification.Type.ORGANIZER_ASSIGNED,
        activity=future,
    ).exists()

    # второй участник остался участником
    assert Participation.objects.filter(
        activity=future, user=later_participant, status=Participation.Status.ACCEPTED,
    ).exists()

    # прошлая активность не тронута
    assert past.status == Activity.Status.ACTIVE


def test_organizer_deletion_cancels_activity_when_no_participants(
    auth_client,
    user,
    activity_factory,
):
    """
    Если у активности нет участников, передавать некому — активность отменяется.
    """
    from datetime import timedelta
    from django.utils import timezone

    now = timezone.now()
    lonely = activity_factory(
        organizer=user,
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=1, hours=2),
    )

    delete_response = auth_client.delete('/me')
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT

    lonely.refresh_from_db()
    assert lonely.status == Activity.Status.CANCELLED


def test_organizer_deletion_notifies_pending_requests_on_cancel(
    auth_client,
    user,
    user_factory,
    activity_factory,
    participation_factory,
):
    """
    При отмене активности (передавать некому) pending-заявкам тоже
    приходит уведомление, чтобы они знали что заявка уже не будет рассмотрена.
    """
    from datetime import timedelta
    from django.utils import timezone
    from notifications.models import Notification

    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
        requires_approval=True,
    )
    pending_user = user_factory()
    participation_factory(activity, pending_user, status=Participation.Status.PENDING)

    delete_response = auth_client.delete('/me')
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT

    activity.refresh_from_db()
    assert activity.status == Activity.Status.CANCELLED
    assert Notification.objects.filter(
        user=pending_user,
        type=Notification.Type.ACTIVITY_CANCELLED,
        activity=activity,
    ).exists()


def test_decline_organizership_passes_activity_to_next_participant(
    auth_client,
    user,
    user_factory,
    activity_factory,
    participation_factory,
):
    """
    Текущий организатор может отказаться через POST /decline-organizership.
    Активность переходит к следующему участнику по дате присоединения.
    Бывший организатор остаётся в активности как обычный accepted-участник —
    если не захочет идти, может выйти стандартным DELETE /participants/me.
    """
    from datetime import timedelta
    from django.utils import timezone

    now = timezone.now()
    activity = activity_factory(
        organizer=user,
        start_at=now + timedelta(days=1),
        end_at=now + timedelta(days=1, hours=2),
    )
    next_in_line = user_factory()
    participation_factory(activity, next_in_line, status=Participation.Status.ACCEPTED)

    response = auth_client.post(
        f'/activities/{activity.id}/decline-organizership', {}, format='json',
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    activity.refresh_from_db()
    assert activity.status == Activity.Status.ACTIVE
    assert activity.organizer_id == next_in_line.id

    # бывший организатор остался в активности как accepted-участник
    assert Participation.objects.filter(
        activity=activity,
        user=user,
        status=Participation.Status.ACCEPTED,
    ).exists()


def test_decline_organizership_cancels_when_no_one_left(
    auth_client,
    user,
    activity_factory,
):
    """Если отказывается единственный организатор и участников нет — отмена."""
    from datetime import timedelta
    from django.utils import timezone

    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )

    response = auth_client.post(
        f'/activities/{activity.id}/decline-organizership', {}, format='json',
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    activity.refresh_from_db()
    assert activity.status == Activity.Status.CANCELLED


def test_decline_organizership_forbidden_for_non_organizer(
    api_client,
    user,
    other_user,
    activity_factory,
):
    """Отказаться от роли может только текущий организатор."""
    from datetime import timedelta
    from django.utils import timezone

    activity = activity_factory(
        organizer=user,
        start_at=timezone.now() + timedelta(days=1),
        end_at=timezone.now() + timedelta(days=1, hours=2),
    )
    api_client.force_authenticate(user=other_user)

    response = api_client.post(
        f'/activities/{activity.id}/decline-organizership', {}, format='json',
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_user_snippet_includes_is_deleted_flag(api_client, user, activity_factory):
    """
    На карточке активности организатор отдаётся через UserSnippetSerializer
    с полем is_deleted — фронт по нему отрисовывает удалённого организатора серым.
    """
    from django.utils import timezone

    activity = activity_factory(organizer=user)

    api_client.force_authenticate(user=user)
    detail = api_client.get(f'/activities/{activity.id}')
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()['organizer']['is_deleted'] is False

    # помечаем юзера как удалённого
    user.deleted_at = timezone.now()
    user.save(update_fields=['deleted_at'])

    detail_after = api_client.get(f'/activities/{activity.id}')
    assert detail_after.json()['organizer']['is_deleted'] is True


def test_qr_token_issue_and_scan(
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
    assert 'expires_at' in created_body
    assert QrToken.objects.filter(user=user).count() == 1

    activity = activity_factory(organizer=other_user)
    participation = participation_factory(activity, user, status=Participation.Status.ACCEPTED)

    api_client.force_authenticate(user=other_user)
    scanned = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': created_body['token']},
        format='json',
    )
    participation.refresh_from_db()
    assert scanned.status_code == status.HTTP_200_OK
    # успешный скан возвращает данные отсканированного юзера и новый статус
    body = scanned.json()
    assert body['user']['id'] == str(user.id)
    assert body['status'] == Participation.Status.ATTENDED
    assert participation.status == Participation.Status.ATTENDED
    assert participation.attendance_marked_at is not None

    # просроченный токен — скан отдаёт TOKEN_EXPIRED
    expired = qr_token_factory(
        user=user,
        token='qr:expired',
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    expired_response = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': expired.token},
        format='json',
    )
    assert expired_response.status_code == status.HTTP_400_BAD_REQUEST
    assert expired_response.json()['error']['code'] == 'TOKEN_EXPIRED'


def test_qr_scan_rejects_non_participant(
    api_client, user, other_user, user_factory, activity_factory, qr_token_factory,
):
    """Сканирование юзера, который не записан на активность → NOT_PARTICIPANT."""
    activity = activity_factory(organizer=other_user)
    not_a_participant = user_factory()
    token = qr_token_factory(user=not_a_participant)

    api_client.force_authenticate(user=other_user)
    response = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': token.token},
        format='json',
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'NOT_PARTICIPANT'


def test_qr_scan_rejects_already_attended(
    api_client, user, other_user, activity_factory, participation_factory, qr_token_factory,
):
    """Повторное сканирование уже отмеченного юзера → ALREADY_ATTENDED."""
    activity = activity_factory(organizer=other_user)
    participation_factory(activity, user, status=Participation.Status.ATTENDED)
    token = qr_token_factory(user=user)

    api_client.force_authenticate(user=other_user)
    response = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': token.token},
        format='json',
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'ALREADY_ATTENDED'


def test_qr_scan_rejects_organizer_themselves(
    api_client, user, other_user, activity_factory, qr_token_factory,
):
    """
    Если организатор сам себя сканирует (QR от своего же аккаунта) — IS_ORGANIZER.
    Маловероятный, но защищаем от случая.
    """
    activity = activity_factory(organizer=other_user)
    # QR-токен принадлежит самому организатору
    token = qr_token_factory(user=other_user)

    api_client.force_authenticate(user=other_user)
    response = api_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': token.token},
        format='json',
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'IS_ORGANIZER'


def test_qr_scan_requires_organizer(auth_client, user, other_user, activity_factory, qr_token_factory):
    activity = activity_factory(organizer=other_user)
    token = qr_token_factory(user=user)

    response = auth_client.post(
        f'/activities/{activity.id}/attendance/scan',
        {'token': token.token},
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


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
