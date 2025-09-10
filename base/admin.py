from django.contrib import admin

from base.models import Chat, College, Feedback, Message, WaitingListEntry

# Register your models here.

admin.site.register(College)
admin.site.register(WaitingListEntry)
admin.site.register(Chat)
admin.site.register(Message)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'comments_preview']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    ordering = ['-created_at']

    def comments_preview(self, obj):
        return obj.comments[:100] + '...' if len(obj.comments) > 100 else obj.comments
    comments_preview.short_description = 'Comments Preview'
