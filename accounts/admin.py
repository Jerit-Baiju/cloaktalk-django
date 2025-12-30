from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, GoogleToken


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'username', 'name', 'college',
                    'is_verified', 'is_service_account', 'is_staff', 'created_at']
    list_filter = ['is_verified', 'is_service_account',
                   'is_staff', 'is_superuser', 'college']
    search_fields = ['email', 'username', 'name']
    ordering = ['-created_at']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('name', 'avatar', 'bio', 'college', 'is_verified', 'is_service_account')
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Additional Info', {
            'fields': ('email', 'name', 'college', 'is_verified', 'is_service_account')
        }),
    )


admin.site.register(GoogleToken)
