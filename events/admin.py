from django.contrib import admin
from .models import Event

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # 一覧画面で表示する項目
    list_display = ('title', 'start_time', 'location', 'is_active')
    # 日付の新しい順に並べる
    ordering = ('-start_time',)