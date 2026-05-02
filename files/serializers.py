from rest_framework import serializers
from .models import File


class FileSerializer(serializers.ModelSerializer):
    id = serializers.CharField()
    class Meta:
        model = File
        fields = ['id', 'original_name', 'mime_type', 'size']
