from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'type',
        'title',
        'action_required',
        'is_read',
        'activity',
        'created_at',
    )
    list_filter = ('type', 'action_required', 'read_at', 'created_at')
    search_fields = (
        'title',
        'message',
        'activity_title',
        'user__email',
        'user__name',
        'request_user__email',
        'request_user__name',
    )
    autocomplete_fields = ('user', 'activity', 'request_user')
    readonly_fields = ('created_at', 'is_read')
    list_select_related = ('user', 'activity', 'request_user')
    ordering = ('-created_at',)
