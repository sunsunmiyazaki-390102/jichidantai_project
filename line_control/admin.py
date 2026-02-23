from django.contrib import admin
from .models import LineSetting

@admin.register(LineSetting)
class LineSettingAdmin(admin.ModelAdmin):
    list_display = ('name', 'updated_at')
    