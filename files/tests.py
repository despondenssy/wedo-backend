import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status

from files.models import File


pytestmark = pytest.mark.django_db


def _real_png_bytes(size=(2, 2), color=(255, 0, 0)):
    """Генерирует валидный PNG минимального размера для тестов загрузки."""
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


def test_file_upload_and_download(auth_client, api_client, settings, file_factory):
    real_bytes = _real_png_bytes()
    upload = SimpleUploadedFile('avatar.png', real_bytes, content_type='image/png')

    created = auth_client.post('/files', {'file': upload}, format='multipart')
    assert created.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get(id=created.json()['id'])
    assert file_obj.original_name == 'avatar.png'
    assert (settings.MEDIA_ROOT / file_obj.storage_key).exists()

    # download is public — no auth required
    downloaded = api_client.get(f'/files/{file_obj.id}')
    assert downloaded.status_code == status.HTTP_200_OK
    # содержимое — то что лежит на диске после обработки, не оригинал
    saved_bytes = (settings.MEDIA_ROOT / file_obj.storage_key).read_bytes()
    assert b''.join(downloaded.streaming_content) == saved_bytes
    assert downloaded['Content-Length'] == str(file_obj.size)

    missing_file = file_factory(name='missing.png')
    (settings.MEDIA_ROOT / missing_file.storage_key).unlink()
    missing = api_client.get(f'/files/{missing_file.id}')
    assert missing.status_code == status.HTTP_404_NOT_FOUND


def test_file_upload_processes_to_jpeg_and_resizes(auth_client, settings, file_factory):
    """
    Загруженное изображение проходит обработку:
    - сохраняется как JPEG независимо от исходного формата
    - ресайзится так чтобы ни одна сторона не превышала MAX_IMAGE_DIMENSION
    - размер на диске меньше оригинала
    """
    # имитируем «сырое фото с телефона» 3000×2250
    real_bytes = _real_png_bytes(size=(3000, 2250))
    upload = SimpleUploadedFile('photo.png', real_bytes, content_type='image/png')

    created = auth_client.post('/files', {'file': upload}, format='multipart')
    assert created.status_code == status.HTTP_201_CREATED

    file_obj = File.objects.get(id=created.json()['id'])

    # после обработки всегда JPEG
    assert file_obj.mime_type == 'image/jpeg'
    assert file_obj.storage_key.endswith('.jpg')

    # после ресайза размер существенно меньше оригинала
    assert file_obj.size < len(real_bytes)

    # реально это валидный JPEG, и размеры в пределах лимита
    saved_path = settings.MEDIA_ROOT / file_obj.storage_key
    with Image.open(saved_path) as img:
        assert img.format == 'JPEG'
        assert max(img.size) <= 1920


def test_file_upload_validation(auth_client):
    no_file = auth_client.post('/files', {}, format='multipart')
    assert no_file.status_code == status.HTTP_400_BAD_REQUEST


def test_file_upload_rejects_fake_image_with_spoofed_mime(auth_client):
    """
    Не-картинка с заявленным image/png Content-Type должна быть отвергнута:
    проверка идёт по реальному содержимому через Pillow, а не по заголовку.
    """
    fake = SimpleUploadedFile('evil.png', b'<?php evil ?>', content_type='image/png')
    response = auth_client.post('/files', {'file': fake}, format='multipart')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'INVALID_FILE_TYPE'


def test_file_upload_rejects_too_large_file(auth_client):
    """Файл больше MAX_UPLOAD_SIZE (10 МБ) отклоняется до парсинга содержимого."""
    big = SimpleUploadedFile(
        'big.png',
        b'\0' * (10 * 1024 * 1024 + 1),
        content_type='image/png',
    )
    response = auth_client.post('/files', {'file': big}, format='multipart')
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error']['code'] == 'FILE_TOO_LARGE'


def test_file_upload_requires_auth(api_client):
    upload = SimpleUploadedFile('avatar.png', _real_png_bytes(), content_type='image/png')
    response = api_client.post('/files', {'file': upload}, format='multipart')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
