from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm, ReadOnlyPasswordHashField
from django import forms

from .models import User, QrToken


class UserCreationForm(forms.ModelForm):
    #два пароля, чтобы админ вводил пароль с подтверждением
    password1 = forms.CharField(label='Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Password confirmation', widget=forms.PasswordInput)
    
    class Meta: #остальные поля берем из модели
        model = User
        fields = ('email', 'name', 'birth_date', 'gender')

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned_data

    #хеширует пароль при сохранении 
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField() #отображается хэш пароля, менять пароль в отдельной форме

    class Meta:
        model = User
        fields = '__all__'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = (
        'id',
        'email',
        'name',
        'gender',
        'rating',
        'city_title',
        'is_active',
        'is_staff',
        'created_at',
    )
    list_filter = ('gender', 'is_active', 'is_staff', 'is_superuser', 'show_birth_date', 'created_at')
    search_fields = ('email', 'name', 'city_title', 'city_settlement', 'city_region', 'city_country')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'last_login')
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = ( #настраивает структуру при редактировании существующего пользователя
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('name', 'birth_date', 'gender', 'avatar_url', 'rating', 'interests')}),
        (
            'City',
            {
                'fields': (
                    'city_settlement',
                    'city_region',
                    'city_country',
                    'city_latitude',
                    'city_longitude',
                    'city_title',
                )
            },
        ),
        (
            'Privacy',
            {
                'fields': (
                    'show_avatar',
                    'show_gender',
                    'show_city_place',
                    'show_interests',
                    'show_birth_date',
                    'show_attendance_history',
                    'show_reviews',
                )
            },
        ),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'created_at', 'updated_at', 'deleted_at')}),
    )

    add_fieldsets = ( #короткая форма при создании нового пользователя
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'name', 'birth_date', 'gender', 'password1', 'password2'),
            },
        ),
    )


@admin.register(QrToken)
class QrTokenAdmin(admin.ModelAdmin):
    list_display = ('id', 'token', 'user', 'expires_at', 'used_at', 'is_expired', 'created_at')
    list_filter = ('used_at', 'expires_at', 'created_at')
    search_fields = ('token', 'user__email', 'user__name')
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'is_expired')

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = ['created_at']
        if obj is not None: #не показывает is_expired при создании объекта
            readonly_fields.append('is_expired')
        return tuple(readonly_fields)
