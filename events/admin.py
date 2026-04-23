from django.contrib import admin
from .models import Event
from .models import EventPhoto

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # 一覧画面で表示する項目
    list_display = ('title', 'start_time', 'location', 'is_active')
    # 日付の新しい順に並べる
    ordering = ('-start_time',)

@admin.register(EventPhoto)
class EventPhotoAdmin(admin.ModelAdmin):
    list_display = ('title', 'image', 'uploaded_at')
        