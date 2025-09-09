from django.contrib import admin
from .models import College, WaitingListEntry

# Register your models here.

admin.site.register(College)
admin.site.register(WaitingListEntry)
