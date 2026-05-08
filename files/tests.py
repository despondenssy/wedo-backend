import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from files.models import File


pytestmark = pytest.mark.django_db


def test_file_upload_and_download(auth_client, api_client, settings, file_factory):
    upload = SimpleUploadedFile('avatar.png', b'png-bytes', content_type='image/png')

    created = auth_client.post('/files', {'file': upload}, format='multipart')
    assert created.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get(id=created.json()['id'])
    assert file_obj.original_name == 'avatar.png'
    assert (settings.MEDIA_ROOT / file_obj.storage_key).exists()

    # download is public — no auth required
    downloaded = api_client.get(f'/files/{file_obj.id}')
    assert downloaded.status_code == status.HTTP_200_OK
    assert b''.join(downloaded.streaming_content) == b'png-bytes'
    assert downloaded['Content-Length'] == str(file_obj.size)

    missing_file = file_factory(name='missing.png')
    (settings.MEDIA_ROOT / missing_file.storage_key).unlink()
    missing = api_client.get(f'/files/{missing_file.id}')
    assert missing.status_code == status.HTTP_404_NOT_FOUND


def test_file_upload_validation(auth_client):
    no_file = auth_client.post('/files', {}, format='multipart')
    assert no_file.status_code == status.HTTP_400_BAD_REQUEST

    bad_file = SimpleUploadedFile('notes.txt', b'text', content_type='text/plain')
    invalid = auth_client.post('/files', {'file': bad_file}, format='multipart')
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST


def test_file_upload_requires_auth(api_client):
    upload = SimpleUploadedFile('avatar.png', b'png-bytes', content_type='image/png')
    response = api_client.post('/files', {'file': upload}, format='multipart')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
