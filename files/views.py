import io
import os
import uuid

from PIL import Image, UnidentifiedImageError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.http import FileResponse

from .models import File
from .serializers import FileSerializer


# реальный формат, отдаваемый Pillow → (наш канонический MIME, расширение для хранения).
# заявленный клиентом Content-Type не используется — он легко подделывается.
ALLOWED_IMAGE_FORMATS = {
    'JPEG': ('image/jpeg', '.jpg'),
    'PNG':  ('image/png', '.png'),
    'WEBP': ('image/webp', '.webp'),
    'GIF':  ('image/gif', '.gif'),
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 МБ


class FileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'Файл обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if file.size > MAX_FILE_SIZE:
            return Response(
                {'error': {
                    'code': 'FILE_TOO_LARGE',
                    'message': f'Размер файла превышает {MAX_FILE_SIZE // (1024 * 1024)} МБ',
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Считываем содержимое и проверяем реальный формат через Pillow.
        # Заявленный клиентом Content-Type не доверяем: его легко подделать,
        # отправив, например, скрипт с заголовком image/png.
        file_bytes = file.read()
        try:
            with Image.open(io.BytesIO(file_bytes)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(file_bytes)) as img:
                detected_format = img.format
        except (UnidentifiedImageError, Exception):
            return Response(
                {'error': {'code': 'INVALID_FILE_TYPE', 'message': 'Файл не является валидным изображением'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if detected_format not in ALLOWED_IMAGE_FORMATS:
            return Response(
                {'error': {'code': 'INVALID_FILE_TYPE', 'message': 'Поддерживаются JPEG, PNG, WEBP, GIF'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actual_mime, ext = ALLOWED_IMAGE_FORMATS[detected_format]

        # Имя файла на диске генерируем сами — расширение по реальному формату,
        # имя через uuid (исключаем коллизии и path-traversal через имя клиента).
        storage_key = f"activities/{uuid.uuid4().hex}{ext}"
        full_path = os.path.join(settings.MEDIA_ROOT, storage_key)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(file_bytes)

        file_obj = File.objects.create(
            storage_key=storage_key,
            original_name=file.name,
            mime_type=actual_mime,  # сохраняем реальный MIME, не client-supplied
            size=len(file_bytes),
        )

        return Response(FileSerializer(file_obj).data, status=status.HTTP_201_CREATED)


class FileDetailView(APIView):

    def get(self, request, file_id):
        file = get_object_or_404(File, id=file_id)
        full_path = os.path.join(settings.MEDIA_ROOT, file.storage_key)

        if not os.path.exists(full_path):
            return Response(
                {'error': {'code': 'FILE_NOT_FOUND', 'message': 'Файл не найден на диске'}},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(
            open(full_path, 'rb'),
            content_type=file.mime_type,
            as_attachment=False,
        )
        response['Content-Length'] = file.size
        response['Cache-Control'] = 'max-age=86400'
        return response
