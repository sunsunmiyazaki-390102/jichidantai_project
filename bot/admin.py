from django.contrib import admin
from .models import MessageLog
from .models import Politician, Event, Course, CourseContent, UserProgress

@admin.register(Politician)
class PoliticianAdmin(admin.ModelAdmin):
    # 一覧画面での表示項目に「アシスタントID有」を追加
    list_display = ('name', 'slug', 'ai_model_name', 'has_api_key', 'has_assistant_id')
    search_fields = ('name', 'slug')

    # ★超便利機能：編集画面を綺麗にグループ分け（セクション化）します
    fieldsets = (
        ('基本情報', {
            'fields': ('name', 'slug')
        }),
        ('LINE連携設定', {
            'fields': ('line_channel_secret', 'line_access_token')
        }),
        ('AI（頭脳）設定', {
            'fields': ('openai_api_key', 'ai_model_name', 'system_prompt', 'openai_assistant_id'),
            'description': '通常のAIを使う場合はプロンプトを、PDFなどの独自知識（RAG）を使う場合はアシスタントIDを入力してください。'
        }),
    )

    def has_api_key(self, obj):
        return bool(obj.openai_api_key)
    has_api_key.short_description = "APIキー設定済"
    has_api_key.boolean = True  # ✓や✕のアイコンで表示されます

    # アシスタントIDが設定されているか判定するメソッドを追加
    def has_assistant_id(self, obj):
        return bool(obj.openai_assistant_id)
    has_assistant_id.short_description = "アシスタント有"
    has_assistant_id.boolean = True

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'date')
    list_filter = ('politician', 'date')
    search_fields = ('title',)

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'video_url_status')
    list_filter = ('politician',)
    search_fields = ('title',)

    def video_url_status(self, obj):
        return "設定済" if obj.video_url else "未設定"
    video_url_status.short_description = "動画登録"

@admin.register(CourseContent)
class CourseContentAdmin(admin.ModelAdmin):
    # 教材タイトルだけでなく、コース名や順番も表示
    list_display = ('course', 'order', 'title', 'video_url')
    # ★超便利機能：一覧画面からそのまま「配信順序(order)」の数字を書き換えられるようにします
    list_editable = ('order',)
    # 政治家ごと、コースごとに絞り込み可能に
    list_filter = ('course__politician', 'course')
    search_fields = ('title', 'message_text')
    ordering = ('course', 'order')

@admin.register(UserProgress)
class UserProgressAdmin(admin.ModelAdmin):
    # 最終更新日時（いつ学習を進めたか）を表示に追加
    list_display = ('line_user_id', 'politician', 'current_course', 'last_completed_order', 'updated_at')
    list_filter = ('politician', 'current_course')
    search_fields = ('line_user_id',)
    readonly_fields = ('updated_at',)

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('member', 'role', 'text_summary', 'created_at', 'is_escalated')
    list_filter = ('role', 'is_escalated', 'created_at')
    search_fields = ('text', 'member__real_name', 'member__display_name')
    readonly_fields = ('created_at',) 

    def text_summary(self, obj):
        return obj.text[:30] + "..." if len(obj.text) > 30 else obj.text
    text_summary.short_description = "内容（抜粋）"
    