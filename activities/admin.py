from django.contrib import admin

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'organizer',
        'category_id',
        'format',
        'status',
        'start_at',
        'requires_approval',
        'created_at',
    )
    list_filter = (
        'format',
        'status',
        'requires_approval',
        'pref_gender',
        'pref_level',
        'created_at',
        'start_at',
    )
    search_fields = (
        'title',
        'description',
        'category_id',
        'subcategory_id',
        'location_address',
        'location_name',
        'location_settlement',
        'organizer__email',
        'organizer__name',
    )
    autocomplete_fields = ('organizer',)
    readonly_fields = ('created_at', 'updated_at', 'cancelled_at')
    list_select_related = ('organizer',)
    ordering = ('-created_at',)

    fieldsets = (
        (None, {'fields': ('organizer', 'title', 'description', 'status')}),
        ('Classification', {'fields': ('category_id', 'subcategory_id', 'format', 'price')}),
        (
            'Location',
            {
                'fields': (
                    'location_latitude',
                    'location_longitude',
                    'location_address',
                    'location_name',
                    'location_settlement',
                )
            },
        ),
        ('Schedule', {'fields': ('start_at', 'end_at', 'time_zone')}),
        (
            'Participation settings',
            {
                'fields': (
                    'requires_approval',
                    'pref_gender',
                    'pref_age_from',
                    'pref_age_to',
                    'pref_level',
                    'pref_max_participants',
                )
            },
        ),
        ('Media', {'fields': ('photo_file_ids',)}),
        ('Important dates', {'fields': ('created_at', 'updated_at', 'cancelled_at')}),
    )
