# чтобы Django при старте подхватил Celery-приложение и декоратор @shared_task знал о нём
from .celery import app as celery_app

__all__ = ('celery_app',)
