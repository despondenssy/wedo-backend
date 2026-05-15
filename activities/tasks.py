"""Фоновые задачи для активностей — импорт и очистка KudaGo-событий."""

import logging

from celery import shared_task
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task
def kudago_import():
    """Ежедневный импорт событий из KudaGo API.

    Вызывается по расписанию Celery beat (3:00 MSK).
    Импортирует события для всех городов на 30 дней вперёд.
    """
    logger.info("KudaGo import: запуск импорта для всех городов...")
    try:
        call_command("import_kudago", "--days-ahead", "30")
    except Exception as exc:
        logger.error("KudaGo import: ошибка при импорте: %s", exc)

    logger.info("KudaGo import: импорт завершён.")


@shared_task
def kudago_cleanup():
    """Очистка неактуальных KudaGo-событий.

    Удаляет события, у которых:
    - source = 'kudago'
    - organizer IS NULL (никто не стал организатором)
    - end_at < now() (уже закончились)

    Вызывает management command cleanup_kudago.
    """
    logger.info("KudaGo cleanup: запуск очистки...")
    try:
        call_command("cleanup_kudago")
    except Exception as exc:
        logger.error("KudaGo cleanup: ошибка: %s", exc)
    logger.info("KudaGo cleanup: завершено.")
