from django.contrib import admin, messages
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget

# 古いGarbageScheduleは削除し、GarbageCalendarを含めてインポートします
from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, MessageLog, GarbageCalendar, EmergencyEvent, EmergencyResponse
from linebot import LineBotApi
from linebot.models import TextSendMessage, QuickReply, QuickReplyButton, PostbackAction

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

# ==========================================
# 防災・アンケート配信の管理画面
# ==========================================

class EmergencyResponseInline(admin.TabularInline):
    """イベント作成画面の「中」に、回答結果を一覧表示させるパネル（UX向上）"""
    model = EmergencyResponse
    extra = 0
    # 回答結果はシステムが自動記録するため、人間が手動で書き換えられないようにする
    readonly_fields = ('ai_member', 'answer', 'replied_at')
    can_delete = False
    
    def has_add_permission(self, request, obj):
        return False # 人間が手動ででっち上げの回答を追加できないようにする防衛策

@admin.action(description="選択した配信をLINEで一斉（または絞り込み）送信する")
def broadcast_emergency_message(modeladmin, request, queryset):
    """一覧画面から選択したイベントをLINEへ送信するアクション（セグメント配信対応版）"""
    for event in queryset:
        if not event.is_active:
            messages.warning(request, f'「{event.title}」は受付中ではないため送信をスキップしました。')
            continue

        politician = event.politician
        if not politician.line_access_token: # ※前回修正した変数名（line_access_token等）に合わせてください
            messages.error(request, f'エラー：{politician} のLINEアクセストークンが設定されていないため送信できません。')
            continue

        try:
            line_bot_api = LineBotApi(politician.line_access_token)

            # クイックリプライ（ボタン）を作成
            items = []
            if event.choice_1: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_1[:20], data=f"action=emergency&event_id={event.id}&ans=1", display_text=event.choice_1)))
            if event.choice_2: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_2[:20], data=f"action=emergency&event_id={event.id}&ans=2", display_text=event.choice_2)))
            if event.choice_3: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_3[:20], data=f"action=emergency&event_id={event.id}&ans=3", display_text=event.choice_3)))

            # 送信するメッセージ本体
            message_text = f"【{event.title}】\n\n{event.message_body}"
            if items:
                message = TextSendMessage(text=message_text, quick_reply=QuickReply(items=items))
            else:
                message = TextSendMessage(text=message_text) # ボタンなしの単なるお知らせも送れるように改善

            # ==========================================
            # ▼ 送信対象者（LINE ID）のリストアップ処理
            # ==========================================
            target_line_user_ids = set() # 重複を防ぐための箱

            if event.target_past_event and event.target_past_answer:
                # 【条件1】過去のイベントで特定の回答（「参加する」など）をした人を抽出
                responses = EmergencyResponse.objects.filter(event=event.target_past_event, answer=event.target_past_answer)
                for r in responses:
                    if r.ai_member and r.ai_member.line_user_id:
                        target_line_user_ids.add(r.ai_member.line_user_id)

            elif event.target_group:
                # 【条件2】特定の班（名簿のグループ1）の人を抽出
                from members.models import TenantMemberProfile
                profiles = TenantMemberProfile.objects.filter(politician=politician, group_1=event.target_group).exclude(ai_member__isnull=True)
                for p in profiles:
                    if p.ai_member and p.ai_member.line_user_id:
                        target_line_user_ids.add(p.ai_member.line_user_id)

            else:
                # 【条件なし】自団体のLINE連携済みユーザー全員を抽出
                from members.models import AiMember
                members = AiMember.objects.filter(politician=politician).exclude(line_user_id__isnull=True)
                for m in members:
                    target_line_user_ids.add(m.line_user_id)

            # リスト化
            target_list = list(target_line_user_ids)

            if not target_list:
                messages.warning(request, f'「{event.title}」の送信対象者が見つかりませんでした。')
                continue

            # ==========================================
            # ▼ 狙い撃ち送信（マルチキャスト）の実行
            # ==========================================
            # LINEの仕様で1回に500人までしか送れないため、500人ずつに分割して送る安全処理
            chunk_size = 500
            for i in range(0, len(target_list), chunk_size):
                chunk = target_list[i:i + chunk_size]
                line_bot_api.multicast(chunk, message)
                
            messages.success(request, f'「{event.title}」を {len(target_list)} 名に送信しました！')

        except Exception as e:
            messages.error(request, f'「{event.title}」の送信中にエラーが発生しました: {e}')

@admin.register(EmergencyEvent)
class EmergencyEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'is_active', 'created_at')
    list_filter = ('politician', 'is_active')
    search_fields = ('title', 'message_body')
    
    # ここで先ほどのインラインパネルを組み込む
    inlines = [EmergencyResponseInline]

    # 【追記】アクションとして登録する
    actions = [broadcast_emergency_message]    

    def get_queryset(self, request):
        """【防衛策】テナント分離（一覧画面に他団体の配信を見せない）"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(politician__admin_users=request.user).distinct()

    def get_form(self, request, obj=None, **kwargs):
        """【防衛策】一般管理者がメッセージを作成する際、間違えて他団体を選べないようにする"""
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and 'politician' in form.base_fields:
            # 「所属団体」のドロップダウンの選択肢を、自分が管理している団体だけに絞り込む
            form.base_fields['politician'].queryset = form.base_fields['politician'].queryset.filter(admin_users=request.user)
        return form

    def save_model(self, request, obj, form, change):
        """【防衛策】保存時に、操作者の自治体を裏側で強制的にセットする"""
        if not request.user.is_superuser and not obj.politician_id:
            tenant = Politician.objects.filter(admin_users=request.user).first()
            if tenant:
                obj.politician = tenant
        super().save_model(request, obj, form, change)

@admin.register(EmergencyResponse)
class EmergencyResponseAdmin(ImportExportModelAdmin):
    """CSVエクスポート機能を持たせた「回答集計専用」の管理画面"""
    list_display = ('event', 'ai_member', 'answer', 'replied_at')
    # イベントごと、または回答（無事/助けが必要など）ごとに絞り込めるようにする
    list_filter = ('event__politician', 'event', 'answer')
    
    def get_queryset(self, request):
        """【防衛策】テナント分離（他団体の回答結果を絶対に見せない）"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(event__politician__admin_users=request.user).distinct()
