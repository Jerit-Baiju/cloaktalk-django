from django.contrib import admin

from .models import Chat, College, Message, WaitingListEntry

# Register your models here.

admin.site.register(College)
admin.site.register(WaitingListEntry)
admin.site.register(Chat)
admin.site.register(Message)
