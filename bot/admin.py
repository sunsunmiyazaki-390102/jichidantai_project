from django.contrib import admin
from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, MessageLog

# 自治会の編集画面の中に「案内の紐付け」を出す設定
class CourseAssignmentInline(admin.TabularInline):
    model = CourseAssignment
    extra = 1
    verbose_name = "割り当てる案内情報"
    verbose_name_plural = "案内情報の割り当て"

# 案内の編集画面の中に「メッセージ内容」を出す設定
class CourseContentInline(admin.StackedInline):
    model = CourseContent
    extra = 1
    verbose_name = "メッセージ内容（ステップ）"
    verbose_name_plural = "メッセージ内容（ステップ）"

@admin.register(Politician)
class PoliticianAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'gomi_region', 'has_api_key')
    # 自治会の編集画面に「案内の紐付け」を表示
    inlines = [CourseAssignmentInline]
    
    fieldsets = (
        ('基本情報', {'fields': ('name', 'slug')}),
        ('LINE連携設定', {'fields': ('line_channel_secret', 'line_access_token')}),
        ('地域設定', {'fields': ('gomi_region',)}),
        ('AI（頭脳）設定', {
            'fields': ('openai_api_key', 'ai_model_name', 'system_prompt', 'openai_assistant_id'),
        }),
    )

    def has_api_key(self, obj):
        return bool(obj.openai_api_key)
    has_api_key.boolean = True
    has_api_key.short_description = "APIキー設定済"

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title',)
    # 案内の編集画面に「メッセージ内容」を表示
    inlines = [CourseContentInline]

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'date')
    list_filter = ('politician',)

@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    list_display = ('line_user_id', 'politician', 'current_course', 'updated_at')

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('member', 'role', 'created_at')