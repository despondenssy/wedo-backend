from django.contrib import admin

from .models import File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'original_name',
        'mime_type',
        'size',
        'storage_key',
        'created_at',
    )
    list_filter = ('mime_type', 'created_at')
    search_fields = ('original_name', 'storage_key', 'mime_type')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
