from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget

# 古いGarbageScheduleは削除し、GarbageCalendarを含めてインポートします
from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, MessageLog, GarbageCalendar

# ==========================================
# 🛡️ 運営側の防衛的措置：テナント分離用・基底クラス
# ==========================================
class TenantIsolationAdmin(admin.ModelAdmin):
    """
    ログインユーザーの権限に応じて表示データを物理的に分離する基底クラス。
    各Adminクラスで `tenant_filter_field` を指定して使用する。
    """
    tenant_filter_field = 'politician__admin_users' # デフォルトのフィルタ条件

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # スーパーユーザー（開発者）は全件表示
        if request.user.is_superuser:
            return qs
        # 一般管理者（自治会担当者）は自身の担当テナントのみ表示（重複排除）
        return qs.filter(**{self.tenant_filter_field: request.user}).distinct()

# ==========================================
# インライン設定
# ==========================================
class CourseAssignmentInline(admin.TabularInline):
    model = CourseAssignment
    extra = 1
    verbose_name = "割り当てる案内情報"
    verbose_name_plural = "案内情報の割り当て"

class CourseContentInline(admin.StackedInline):
    model = CourseContent
    extra = 1
    verbose_name = "メッセージ内容（ステップ）"
    verbose_name_plural = "メッセージ内容（ステップ）"

# ==========================================
# 管理画面の登録
# ==========================================
@admin.register(Politician)
class PoliticianAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug','gomi_municipality', 'gomi_district', 'has_api_key')
    inlines = [CourseAssignmentInline]
    
    # 【防衛的仕様】誤操作による権限削除を防ぐための左右分割UI
    filter_horizontal = ('admin_users',)
    
    fieldsets = (
        ('基本情報・システム権限', {
            'fields': ('name', 'slug', 'admin_users') # ← admin_users を追加
        }),
        ('LINE連携設定', {'fields': ('line_channel_secret', 'line_access_token')}),
        ('地域設定', {'fields': ('gomi_municipality', 'gomi_district')}),
        ('AI（頭脳）設定', {
            'fields': ('openai_api_key', 'ai_model_name', 'system_prompt', 'openai_assistant_id'),
        }),
    )

    def has_api_key(self, obj):
        return bool(obj.openai_api_key)
    has_api_key.boolean = True
    has_api_key.short_description = "APIキー設定済"

    # 自治会マスタ自体のテナント分離
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(admin_users=request.user)

@admin.register(Course)
class CourseAdmin(TenantIsolationAdmin):
    # CourseはCourseAssignmentを通じてPoliticianに紐づくためフィルタ条件を変更
    tenant_filter_field = 'courseassignment__politician__admin_users'
    list_display = ('title',)
    inlines = [CourseContentInline]

@admin.register(Event)
class EventAdmin(TenantIsolationAdmin):
    tenant_filter_field = 'politician__admin_users'
    list_display = ('title', 'politician', 'date')
    list_filter = ('politician',)

@admin.register(UserProgress)
class UserProgressAdmin(TenantIsolationAdmin):
    tenant_filter_field = 'politician__admin_users'
    list_display = ('line_user_id', 'politician', 'current_course', 'updated_at')

@admin.register(MessageLog)
class MessageLogAdmin(TenantIsolationAdmin):
    # MessageLog は AiMember (member) を経由して Politician に紐づく想定
    tenant_filter_field = 'member__politician__admin_users'
    list_display = ('member', 'role', 'created_at')

# ==========================================
# GarbageCalendar 用のインポート設定
# ==========================================
class GarbageCalendarResource(resources.ModelResource):
    collection_date = fields.Field(attribute='collection_date', column_name='日付', widget=DateWidget(format='%Y/%m/%d'))
    municipality = fields.Field(attribute='municipality', column_name='市町村')
    district = fields.Field(attribute='district', column_name='地区')
    garbage_type = fields.Field(attribute='garbage_type', column_name='ごみ種別')
    other = fields.Field(attribute='other', column_name='その他')

    class Meta:
        model = GarbageCalendar
        import_id_fields = ('municipality', 'district', 'collection_date', 'garbage_type')
        skip_unchanged = True

    def skip_row(self, instance, original, row, import_validation_errors=None):
        if not row.get('日付') or str(row.get('日付')).strip() == '':
            return True
        return super().skip_row(instance, original, row, import_validation_errors=import_validation_errors)

@admin.register(GarbageCalendar)
class GarbageCalendarAdmin(ImportExportModelAdmin):
    resource_class = GarbageCalendarResource
    list_display = ('collection_date', 'municipality', 'district', 'garbage_type')
    list_filter = ('municipality', 'district')
    search_fields = ('garbage_type', 'notes')
    date_hierarchy = 'collection_date'

    # ゴミカレンダーのテナント分離（市町村名による動的マッチング）
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        
        # ログインユーザーが管理する自治会の「市町村名」リストを取得
        allowed_municipalities = Politician.objects.filter(
            admin_users=request.user
        ).values_list('gomi_municipality', flat=True)
        
        # 該当する市町村のゴミデータのみ許可
        return qs.filter(municipality__in=allowed_municipalities)
    