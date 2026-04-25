from django.contrib import admin
from .models import Event, EventPhoto, Announcement

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # 一覧画面で表示する項目
    list_display = ('title','politician', 'start_time', 'location', 'is_active')
    list_filter = ('politician', 'is_active')
    search_fields = ('title', 'description')
    # 日付の新しい順に並べる
    ordering = ('-start_time',)

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'created_at', 'is_active')
    list_filter = ('politician', 'is_active', 'created_at')
    search_fields = ('title', 'content')    

@admin.register(EventPhoto)
class EventPhotoAdmin(admin.ModelAdmin):
    list_display = ('title', 'image', 'uploaded_at')
        