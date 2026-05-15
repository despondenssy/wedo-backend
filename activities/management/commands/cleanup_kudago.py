"""Management command для очистки устаревших KudaGo-событий и их фото.

Использование:
    python manage.py cleanup_kudago --dry-run
    python manage.py cleanup_kudago
"""

import logging
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from activities.models import Activity
from files.models import File

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Удаляет устаревшие KudaGo-события (source='kudago', organizer=NULL, end_at < now()) и их фото."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Режим проверки: только показать сколько событий будет удалено",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()

        qs = Activity.objects.filter(
            source=Activity.Source.KUDAGO,
            organizer__isnull=True,
            end_at__lt=now,
        )
        count = qs.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("Нет устаревших KudaGo-событий для удаления."))
            return

        # Собираем все file_id из photo_file_ids удаляемых активностей
        all_file_ids: list[int] = []
        for activity in qs.iterator():
            all_file_ids.extend(activity.photo_file_ids or [])

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY-RUN: будет удалено {count} устаревших KudaGo-событий "
                    f"и {len(all_file_ids)} файлов."
                )
            )
            return

        # Удаляем файлы с диска
        deleted_files = 0
        if all_file_ids:
            for file_obj in File.objects.filter(id__in=all_file_ids).iterator():
                full_path = os.path.join(settings.MEDIA_ROOT, file_obj.storage_key)
                try:
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        deleted_files += 1
                except OSError as exc:
                    self.stderr.write(
                        self.style.ERROR(f"Не удалось удалить файл {full_path}: {exc}")
                    )

            # Удаляем записи из таблицы files
            File.objects.filter(id__in=all_file_ids).delete()

        # Удаляем активности
        qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Удалено {count} событий и {deleted_files} файлов."
            )
        )
