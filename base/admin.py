from django.contrib import admin

from base.models import Chat, College, Confession, Feedback, Message, WaitingListEntry

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


@admin.register(Confession)
class ConfessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'author', 'college', 'confession_preview', 'likes_count', 'dislikes_count', 'created_at']
    list_filter = ['college', 'created_at']
    readonly_fields = ['id', 'created_at', 'updated_at', 'likes_count', 'dislikes_count']
    search_fields = ['confession', 'author__email', 'author__name']
    ordering = ['-created_at']
    filter_horizontal = ['likes', 'dislikes']

    def confession_preview(self, obj):
        return obj.confession[:100] + '...' if len(obj.confession) > 100 else obj.confession
    confession_preview.short_description = 'Confession Preview'
