from rest_framework import serializers
from .models import File


class FileSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    originalName = serializers.CharField(source='original_name')
    mimeType = serializers.CharField(source='mime_type')

    class Meta:
        model = File
        fields = ['id', 'originalName', 'mimeType', 'size']
