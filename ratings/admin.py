from django.contrib import admin

from .models import ActivityRating


@admin.register(ActivityRating)
class ActivityRatingAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'activity',
        'user',
        'rating',
        'created_at',
        'updated_at',
    )
    list_filter = ('rating', 'created_at', 'updated_at')
    search_fields = ('activity__title', 'user__email', 'user__name', 'comment')
    autocomplete_fields = ('activity', 'user')
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('activity', 'user')
    ordering = ('-created_at',)
