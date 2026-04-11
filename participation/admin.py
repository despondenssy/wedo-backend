from django.contrib import admin

from .models import Participation


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'activity',
        'user',
        'status',
        'attendance_marked_at',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'attendance_marked_at', 'created_at', 'updated_at')
    search_fields = ('activity__title', 'user__email', 'user__name')
    autocomplete_fields = ('activity', 'user') #поиск вместо выпадающего списка
    readonly_fields = ('created_at', 'updated_at')
    list_select_related = ('activity', 'user')
    ordering = ('-created_at',)
