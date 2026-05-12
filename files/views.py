import io
import os
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.http import FileResponse

from .models import File
from .serializers import FileSerializer


# принимаем "сырые" фото с телефона (типично 3-8 МБ); сжимаются на сервере
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 МБ

# после ресайза ни одна из сторон не больше этого. 1920 — full HD, на экране
# мобилки и листинге всё равно отрисовывается ~800px, оригинал не нужен
MAX_IMAGE_DIMENSION = 1920

# качество JPEG: 85 — стандартный баланс размер/качество, глаз почти не видит
JPEG_QUALITY = 85

# реальные форматы которые принимаем (определяются Pillow'ом по содержимому,
# а не по заявленному Content-Type — клиент мог его подделать)
ALLOWED_INPUT_FORMATS = ('JPEG', 'PNG', 'WEBP', 'GIF')


def _process_image(raw_bytes: bytes) -> bytes:
    """
    Нормализует загруженное изображение перед сохранением:
        1. EXIF-ориентация — телефонные фото бывают с меткой "повернуть на N°";
           без транспонирования отобразятся боком после ре-кодирования
        2. ресайз до MAX_IMAGE_DIMENSION с сохранением пропорций
        3. JPEG quality=85 — универсальный формат, ~30% меньше PNG
        4. побочный эффект: вырезается EXIF — из метаданных могла утечь
           геолокация снимка (приватность пользователей)
    """
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = ImageOps.exif_transpose(img)

        # ресайз только если хоть одна сторона больше лимита (thumbnail умный)
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

        # JPEG не поддерживает прозрачность — для PNG/WebP с альфа-каналом
        # склеиваем на белый фон, иначе при сохранении прозрачность станет чёрным
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        out = io.BytesIO()
        img.save(out, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


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

        if file.size > MAX_UPLOAD_SIZE:
            return Response(
                {'error': {
                    'code': 'FILE_TOO_LARGE',
                    'message': f'Размер файла превышает {MAX_UPLOAD_SIZE // (1024 * 1024)} МБ',
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Проверяем реальный формат через Pillow (заявленный Content-Type не доверяем)
        raw_bytes = file.read()
        try:
            with Image.open(io.BytesIO(raw_bytes)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(raw_bytes)) as img:
                detected_format = img.format
        except (UnidentifiedImageError, Exception):
            return Response(
                {'error': {'code': 'INVALID_FILE_TYPE', 'message': 'Файл не является валидным изображением'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if detected_format not in ALLOWED_INPUT_FORMATS:
            return Response(
                {'error': {'code': 'INVALID_FILE_TYPE', 'message': 'Поддерживаются JPEG, PNG, WEBP, GIF'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Обрабатываем: ресайз + перекодировка в JPEG. После этого хранится
        # уже сжатая копия — место на диске экономится в 5-10 раз.
        processed_bytes = _process_image(raw_bytes)

        # Имя на диске генерируем сами; расширение всегда .jpg т.к. на выходе JPEG
        storage_key = f"activities/{uuid.uuid4().hex}.jpg"
        full_path = os.path.join(settings.MEDIA_ROOT, storage_key)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(processed_bytes)

        file_obj = File.objects.create(
            storage_key=storage_key,
            original_name=file.name,
            mime_type='image/jpeg',
            size=len(processed_bytes),
        )

        return Response(FileSerializer(file_obj).data, status=status.HTTP_201_CREATED)


class FileDetailView(APIView):
    permission_classes = [AllowAny]
    renderer_classes = []

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
