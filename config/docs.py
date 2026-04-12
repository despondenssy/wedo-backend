from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse


OPENAPI_FILE = Path(settings.BASE_DIR) / 'openapi.json'


def openapi_json_view(request):
    if not OPENAPI_FILE.exists():
        raise Http404('openapi.json not found')
    return FileResponse(OPENAPI_FILE.open('rb'), content_type='application/json')


def swagger_ui_view(request):
    schema_url = reverse('openapi-json')
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WeDo API Docs</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.ui = SwaggerUIBundle({{
      url: "{schema_url}",
      dom_id: "#swagger-ui",
      deepLinking: true,
      persistAuthorization: true
    }});
  </script>
</body>
</html>"""
    return HttpResponse(html)
