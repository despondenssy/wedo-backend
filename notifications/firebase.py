import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings
import os

_firebase_initialized = False

def _init_firebase():
    global _firebase_initialized
    if not _firebase_initialized:
        cred_path = os.path.join(settings.BASE_DIR, 'firebase-service-account.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True


def send_push(device_token: str, title: str, body: str, data: dict = None):
    """
    Отправить push-уведомление на конкретное устройство.
    device_token — FCM токен устройства.
    title — заголовок уведомления.
    body — текст уведомления.
    data — дополнительные данные (опционально).
    """
    try:
        _init_firebase()
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data or {},
            token=device_token,
        )
        messaging.send(message)
    except Exception as e:
        # если push не отправился — логируем и идём дальше
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'FCM send error: {e}')


def send_push_to_user(user, title: str, body: str, data: dict = None):
    """
    Отправить push всем устройствам пользователя.
    """
    from notifications.models import DeviceToken
    tokens = DeviceToken.objects.filter(user=user).values_list('token', flat=True)
    for token in tokens:
        send_push(token, title, body, data)
