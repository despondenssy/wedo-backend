import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django

django.setup()

from activities.models import Activity, SavedActivity
from notifications.models import DeviceToken, Notification
from participation.models import Participation
from ratings.models import ActivityRating
from subscriptions.models import Subscription
from users.models import QrToken, User


LOADTEST_PREFIX = 'loadtest'


def main():
    users = User.objects.filter(email__startswith=f'{LOADTEST_PREFIX}_')
    activities = Activity.objects.filter(title__startswith=f'{LOADTEST_PREFIX} ')

    user_ids = list(users.values_list('id', flat=True))
    activity_ids = list(activities.values_list('id', flat=True))

    deleted = {}
    deleted['activity_ratings'] = ActivityRating.objects.filter(
        activity_id__in=activity_ids,
    ).delete()[0] + ActivityRating.objects.filter(user_id__in=user_ids).delete()[0]
    deleted['participations'] = Participation.objects.filter(
        activity_id__in=activity_ids,
    ).delete()[0] + Participation.objects.filter(user_id__in=user_ids).delete()[0]
    deleted['notifications'] = Notification.objects.filter(
        user_id__in=user_ids,
    ).delete()[0] + Notification.objects.filter(activity_id__in=activity_ids).delete()[0]
    deleted['subscriptions'] = Subscription.objects.filter(
        follower_id__in=user_ids,
    ).delete()[0] + Subscription.objects.filter(target_id__in=user_ids).delete()[0]
    deleted['saved_activities'] = SavedActivity.objects.filter(
        user_id__in=user_ids,
    ).delete()[0] + SavedActivity.objects.filter(activity_id__in=activity_ids).delete()[0]
    deleted['qr_tokens'] = QrToken.objects.filter(user_id__in=user_ids).delete()[0]
    deleted['device_tokens'] = DeviceToken.objects.filter(user_id__in=user_ids).delete()[0]
    deleted['activities'] = activities.delete()[0]
    deleted['users'] = users.delete()[0]

    print('Loadtest cleanup finished.')
    for key, value in deleted.items():
        print(f'{key}: {value}')


if __name__ == '__main__':
    main()
