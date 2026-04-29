import json

import pytest
from rest_framework import status


pytestmark = pytest.mark.django_db


def test_openapi_json_and_swagger_ui_are_public(api_client):
    schema = api_client.get('/api/openapi.json')
    assert schema.status_code == status.HTTP_200_OK
    parsed = json.loads(b''.join(schema.streaming_content).decode('utf-8'))
    assert 'paths' in parsed

    swagger = api_client.get('/api/docs/swagger/')
    assert swagger.status_code == status.HTTP_200_OK
    assert b'SwaggerUIBundle' in swagger.content
