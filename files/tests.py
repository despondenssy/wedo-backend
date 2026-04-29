import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from files.models import File


pytestmark = pytest.mark.django_db


def test_file_upload_list_download_and_missing_disk_file(auth_client, settings, file_factory):
    upload = SimpleUploadedFile('avatar.png', b'png-bytes', content_type='image/png')

    created = auth_client.post('/files', {'file': upload}, format='multipart')
    assert created.status_code == status.HTTP_201_CREATED
    file_obj = File.objects.get(id=created.data['id'])
    assert file_obj.original_name == 'avatar.png'
    assert (settings.MEDIA_ROOT / file_obj.storage_key).exists()

    listed = auth_client.get(f'/files?ids={file_obj.id}')
    assert listed.status_code == status.HTTP_200_OK
    assert listed.data['items'][0]['id'] == str(file_obj.id)

    downloaded = auth_client.get(f'/files/{file_obj.id}')
    assert downloaded.status_code == status.HTTP_200_OK
    assert b''.join(downloaded.streaming_content) == b'png-bytes'
    assert downloaded['Content-Length'] == str(file_obj.size)

    missing_file = file_factory(name='missing.png')
    (settings.MEDIA_ROOT / missing_file.storage_key).unlink()
    missing = auth_client.get(f'/files/{missing_file.id}')
    assert missing.status_code == status.HTTP_404_NOT_FOUND


def test_file_upload_validation_and_ids_required(auth_client, file_factory):
    no_file = auth_client.post('/files', {}, format='multipart')
    assert no_file.status_code == status.HTTP_400_BAD_REQUEST

    bad_file = SimpleUploadedFile('notes.txt', b'text', content_type='text/plain')
    invalid = auth_client.post('/files', {'file': bad_file}, format='multipart')
    assert invalid.status_code == status.HTTP_400_BAD_REQUEST

    missing_ids = auth_client.get('/files')
    assert missing_ids.status_code == status.HTTP_400_BAD_REQUEST


def test_files_endpoint_requires_auth(api_client):
    response = api_client.get('/files?ids=1')
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
