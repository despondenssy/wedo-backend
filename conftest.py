#тут лежат фикстуры для тестов
from datetime import date, timedelta
import os
from pathlib import Path
import shutil

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import pytest
from django.utils import timezone
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    # rate limiting хранит счётчики в Django cache;
    # без очистки они переживают между тестами и ломают флоу
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory(db):
    from users.models import User

    counter = {'value': 0}

    def create_user(**kwargs):
        counter['value'] += 1
        n = counter['value']
        defaults = {
            'email': f'user{n}@example.com',
            'password': 'StrongPass123',
            'name': f'User {n}',
            'birth_date': date(1995, 1, min(n, 28)),
            'gender': User.Gender.NOT_GIVEN,
            'interests': ['sport', 'board-games'],
            'city_settlement': 'Moscow',
            'city_region': 'Moscow',
            'city_country': 'Russia',
            'city_latitude': 55.751244,
            'city_longitude': 37.618423,
            'city_title': 'Moscow',
        }
        password = kwargs.pop('password', defaults.pop('password'))
        defaults.update(kwargs)
        return User.objects.create_user(password=password, **defaults)

    return create_user


@pytest.fixture
def user(user_factory):
    return user_factory()


@pytest.fixture
def other_user(user_factory):
    return user_factory()


@pytest.fixture
def auth_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def activity_factory(db, user_factory):
    from activities.models import Activity

    counter = {'value': 0}

    def create_activity(**kwargs):
        counter['value'] += 1
        n = counter['value']
        organizer = kwargs.pop('organizer', None) or user_factory()
        defaults = {
            'organizer': organizer,
            'title': f'Activity {n}',
            'description': f'Description {n}',
            'category_id': 'sport',
            'subcategory_id': 'football',
            'format': Activity.Format.OFFLINE,
            'status': Activity.Status.ACTIVE,
            'location_latitude': 55.75,
            'location_longitude': 37.61,
            'location_address': 'Red Square',
            'location_name': 'Center',
            'location_settlement': 'Moscow',
            'location_region': 'Moscow',
            'location_country': 'Russia',
            'start_at': timezone.now() + timedelta(days=n),
            'end_at': timezone.now() + timedelta(days=n, hours=2),
            'time_zone': 'Europe/Moscow',
            'pref_gender': None,
            'pref_age_from': 18,
            'pref_age_to': 60,
            'pref_level': Activity.Level.BEGINNER,
            'pref_max_participants': None,
            'requires_approval': False,
            'photo_file_ids': [],
            'price': 0,
        }
        defaults.update(kwargs)
        return Activity.objects.create(**defaults)

    return create_activity


@pytest.fixture
def activity(activity_factory, user):
    return activity_factory(organizer=user)


@pytest.fixture
def participation_factory(db):
    def create_participation(activity, user, status='accepted', **kwargs):
        from participation.models import Participation

        return Participation.objects.create(
            activity=activity,
            user=user,
            status=status,
            **kwargs,
        )

    return create_participation


@pytest.fixture
def notification_factory(db):
    def create_notification(user, **kwargs):
        from notifications.models import Notification

        defaults = {
            'type': Notification.Type.SYSTEM,
            'title': 'Notice',
            'message': 'Message',
            'activity': None,
            'request_user': None,
            'activity_title': None,
            'action_required': False,
        }
        defaults.update(kwargs)
        return Notification.objects.create(user=user, **defaults)

    return create_notification


@pytest.fixture
def subscription_factory(db):
    def create_subscription(follower, target, **kwargs):
        from subscriptions.models import Subscription

        return Subscription.objects.create(follower=follower, target=target, **kwargs)

    return create_subscription


@pytest.fixture
def rating_factory(db):
    def create_rating(activity, user, rating=5, comment='Great'):
        from ratings.models import ActivityRating

        return ActivityRating.objects.create(
            activity=activity,
            user=user,
            rating=rating,
            comment=comment,
        )

    return create_rating


@pytest.fixture
def file_factory(db, settings):
    from files.models import File

    media_root = Path(settings.BASE_DIR) / '.test_media'
    shutil.rmtree(media_root, ignore_errors=True)
    media_root.mkdir(parents=True, exist_ok=True)
    settings.MEDIA_ROOT = media_root

    def create_file(name='image.png', content=b'png-bytes', mime_type='image/png'):
        storage_key = f'activities/{name}'
        full_path = Path(settings.MEDIA_ROOT) / storage_key
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return File.objects.create(
            storage_key=storage_key,
            original_name=name,
            mime_type=mime_type,
            size=len(content),
        )

    yield create_file
    shutil.rmtree(media_root, ignore_errors=True)


@pytest.fixture
def qr_token_factory(db):
    def create_qr_token(user, token='qr:test', expires_at=None, used_at=None):
        from users.models import QrToken

        return QrToken.objects.create(
            user=user,
            token=token,
            expires_at=expires_at or timezone.now() + timedelta(minutes=1),
            used_at=used_at,
        )

    return create_qr_token


@pytest.fixture
def feed_event_factory(db):
    def create_feed_event(user, activity, type='created', **kwargs):
        from activities.models import UserActivityFeedEvent

        return UserActivityFeedEvent.objects.create(
            user=user,
            activity=activity,
            type=type,
            occurred_at=kwargs.pop('occurred_at', timezone.now()),
            **kwargs,
        )

    return create_feed_event


@pytest.fixture
def activity_payload():
    start = timezone.now() + timedelta(days=7)
    end = start + timedelta(hours=2)
    return {
        'title': 'New activity',
        'description': 'A detailed description',
        'category_id': 'sport',
        'subcategory_id': 'football',
        'format': 'offline',
        'location': {
            'latitude': 55.75,
            'longitude': 37.61,
            'address': 'Red Square',
            'name': 'Center',
            'settlement': 'Moscow',
            'region': 'Moscow',
            'country': 'Russia',
        },
        'start_at': start.isoformat(),
        'end_at': end.isoformat(),
        'time_zone': 'Europe/Moscow',
        'preferences': {
            'age_from': 18,
            'age_to': 45,
            'level': 'beginner',
            'max_participants': 5,
        },
        'requires_approval': False,
        'photo_file_ids': [],
        'price': '0.00',
    }
