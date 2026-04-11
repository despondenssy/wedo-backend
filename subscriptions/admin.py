from django.contrib import admin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'follower',
        'target',
        'is_pinned',
        'created_at',
        'updated_at',
    )
    list_filter = ('is_pinned', 'created_at', 'updated_at')
    search_fields = (
        'follower__email',
        'follower__name',
        'target__email',
        'target__name',
    )
    autocomplete_fields = ('follower', 'target')
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('follower', 'target')
    ordering = ('-created_at',)
