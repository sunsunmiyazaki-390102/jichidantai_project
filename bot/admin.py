from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget

# 古いGarbageScheduleは削除し、GarbageCalendarを含めてインポートします
from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, MessageLog, GarbageCalendar

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

# === ここから GarbageCalendar 用のインポート設定 ===

# 1. Excel(CSV)の列と、データベースの項目を紐付ける「翻訳辞書」
class GarbageCalendarResource(resources.ModelResource):
    collection_date = fields.Field(attribute='collection_date', column_name='日付', widget=DateWidget(format='%Y/%m/%d'))
    municipality = fields.Field(attribute='municipality', column_name='市町村')
    district = fields.Field(attribute='district', column_name='地区')
    garbage_type = fields.Field(attribute='garbage_type', column_name='ごみ種別')
    other = fields.Field(attribute='other', column_name='その他')

    class Meta:
        model = GarbageCalendar
        # 重複して取り込まないための基準キー（この4つが同じなら「上書き」扱いにする）
        import_id_fields = ('municipality', 'district', 'collection_date', 'garbage_type')
        skip_unchanged = True

# 2. 管理画面にインポート機能を合体させる
@admin.register(GarbageCalendar)
class GarbageCalendarAdmin(ImportExportModelAdmin):
    resource_class = GarbageCalendarResource
    list_display = ('collection_date', 'municipality', 'district', 'garbage_type')
    list_filter = ('municipality', 'district')
    search_fields = ('garbage_type', 'notes')
    date_hierarchy = 'collection_date'
