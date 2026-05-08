import json

from rest_framework import status


def test_openapi_json_and_swagger_ui_are_public(api_client):
    schema = api_client.get('/api/openapi.json')
    assert schema.status_code == status.HTTP_200_OK
    assert schema['Content-Type'] == 'application/json'

    parsed = json.loads(b''.join(schema.streaming_content).decode('utf-8-sig'))
    assert 'openapi' in parsed
    assert 'info' in parsed
    assert 'paths' in parsed
    assert 'components' in parsed

    swagger = api_client.get('/api/docs/swagger/')
    assert swagger.status_code == status.HTTP_200_OK
    assert 'text/html' in swagger['Content-Type']
    assert b'SwaggerUIBundle' in swagger.content

    rapidoc = api_client.get('/api/docs/rapidoc/')
    assert rapidoc.status_code == status.HTTP_200_OK
    assert 'text/html' in rapidoc['Content-Type']
    assert b'rapi-doc' in rapidoc.content
