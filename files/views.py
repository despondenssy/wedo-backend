import os
import uuid
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

ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']


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

        if file.content_type not in ALLOWED_MIME_TYPES:
            return Response(
                {'error': {'code': 'INVALID_FILE_TYPE', 'message': 'Разрешены только изображения'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # генерируем уникальное имя чтобы не было коллизий
        ext = os.path.splitext(file.name)[1]
        storage_key = f"activities/{uuid.uuid4().hex}{ext}"
        full_path = os.path.join(settings.MEDIA_ROOT, storage_key)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'wb') as f:
            for chunk in file.chunks():
                f.write(chunk)

        file_obj = File.objects.create(
            storage_key=storage_key,
            original_name=file.name,
            mime_type=file.content_type,
            size=file.size,
        )

        return Response(FileSerializer(file_obj).data, status=status.HTTP_201_CREATED)

    def get(self, request):
        ids = request.query_params.get('ids', '')
        if not ids:
            return Response(
                {'error': {'code': 'BAD_REQUEST', 'message': 'ids обязателен'}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        id_list = [i.strip() for i in ids.split(',') if i.strip()]
        files = File.objects.filter(id__in=id_list)

        return Response({'items': FileSerializer(files, many=True).data})


class FileDetailView(APIView):
    permission_classes = [IsAuthenticated]

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
