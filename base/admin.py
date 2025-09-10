from django.contrib import admin

from base.models import Chat, College, Message, WaitingListEntry

# Register your models here.

admin.site.register(College)
admin.site.register(WaitingListEntry)
admin.site.register(Chat)


class MessageAdmin(admin.ModelAdmin):
    """Admin for Message: newest messages first in list view."""

    ordering = ("-created_at",)
    list_display = ("id", "chat", "sender", "message_type", "created_at", "is_read")
    list_filter = ("message_type", "is_read")
    search_fields = ("content",)


admin.site.register(Message, MessageAdmin)
