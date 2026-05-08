"""Celery приложение для WeDo.

Запускается командами:
- worker:  celery -A config worker -l info
- beat:    celery -A config beat -l info

Конфигурация читается из Django settings (переменные с префиксом CELERY_).
"""
import os
from celery import Celery


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('wedo')

# забираем настройки из Django settings.py — все переменные с префиксом CELERY_
app.config_from_object('django.conf:settings', namespace='CELERY')

# автоматически подхватывает tasks.py из всех INSTALLED_APPS
app.autodiscover_tasks()
