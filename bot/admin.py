from django.contrib import admin, messages
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import DateWidget
from django.utils.html import format_html

from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, MessageLog, GarbageCalendar, EmergencyEvent, EmergencyResponse, CityAdminProfile, CityEmergencyEvent, CityEmergencyResponse, CityMemberProfile, PublicPageConfig, BroadcastMessage, Municipality, FuneralHall, Condolence, TenantLLMQuota
from linebot import LineBotApi
from linebot.models import TextSendMessage, QuickReply, QuickReplyButton, PostbackAction
from linebot.exceptions import LineBotApiError
from django.shortcuts import render
from django.contrib.admin import helpers
from django.utils import timezone
from members.models import AiMember
from django.conf import settings
from django.utils.safestring import mark_safe

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
    list_display = ('name', 'slug', 'city_code', 'district_code', 'gomi_municipality', 'gomi_district', 'has_api_key')
    inlines = [CourseAssignmentInline]
    
    # 【防衛的仕様】誤操作による権限削除を防ぐための左右分割UI
    filter_horizontal = ('admin_users',)
    
    fieldsets = (
        ('基本情報・システム権限', {
            'fields': ('name', 'slug', 'city_code', 'district_code', 'admin_users') # ← admin_users を追加
        }),
        ('LINE連携設定', {'fields': ('line_channel_secret', 'line_access_token', 'notification_line_id')}),
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

    # ▼▼▼ 新規追加：スーパーユーザー以外はメニューから隠す ▼▼▼
    def has_module_permission(self, request):
        return request.user.is_superuser

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
    # list_filter = ('politician',)

    # ▼▼▼ 新規追加：スーパーユーザー以外はフィルターを隠す ▼▼▼
    def get_list_filter(self, request):
        if request.user.is_superuser:
            return ('politician',)
        return () # 一般役員は空っぽ（フィルターなし）にする

    # ① 一覧画面で「自分の自治会」のデータしか表示させない
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # 自分が admin_users に登録されている自治会のデータだけを返す
        return qs.filter(politician__admin_users=request.user)

    # ② 追加・編集画面の「所属団体」プルダウンで、他団体を選べなくする
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser:
            if 'politician' in form.base_fields:
                form.base_fields['politician'].queryset = form.base_fields['politician'].queryset.filter(admin_users=request.user)
        return form

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
    """一覧画面から選択したイベントをLINEへ送信するアクション（中間確認画面付き）"""
    
    # ==========================================
    # ▼ [第2段階] 「はい、正式に送信する」が押された後の処理
    # ==========================================
    if 'apply' in request.POST:
        for event in queryset:
            if not event.is_active: continue
            politician = event.politician
            try:
                line_bot_api = LineBotApi(politician.line_access_token)
                items = []
                if event.choice_1: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_1[:20], data=f"action=emergency&event_id={event.id}&ans=1", display_text=event.choice_1)))
                if event.choice_2: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_2[:20], data=f"action=emergency&event_id={event.id}&ans=2", display_text=event.choice_2)))
                if event.choice_3: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_3[:20], data=f"action=emergency&event_id={event.id}&ans=3", display_text=event.choice_3)))

                message_text = f"【{event.title}】\n\n{event.message_body}"
                if event.attached_file:
                    file_url = request.build_absolute_uri(event.attached_file.url)
                    message_text += f"\n\n📎 添付ファイル（詳細資料）はこちら:\n{file_url}"

                if items: message = TextSendMessage(text=message_text, quick_reply=QuickReply(items=items))
                else: message = TextSendMessage(text=message_text)

                target_line_user_ids = set()
                if event.target_past_event and event.target_past_answer:
                    for r in EmergencyResponse.objects.filter(event=event.target_past_event, answer=event.target_past_answer):
                        if r.ai_member and r.ai_member.line_user_id: target_line_user_ids.add(r.ai_member.line_user_id)
                elif event.target_group_1 or event.target_group_2 or event.target_group_3 or event.target_note_1 or event.target_note_2 or event.target_note_3:
                    from members.models import TenantMemberProfile
                    filters = {'politician': politician}
                    if event.target_group_1: filters['group_1'] = event.target_group_1
                    if event.target_group_2: filters['group_2'] = event.target_group_2
                    if event.target_group_3: filters['group_3'] = event.target_group_3
                    if event.target_note_1: filters['note_1'] = event.target_note_1
                    if event.target_note_2: filters['note_2'] = event.target_note_2
                    if event.target_note_3: filters['note_3'] = event.target_note_3
                    for p in TenantMemberProfile.objects.filter(**filters).exclude(ai_member__isnull=True):
                        if p.ai_member and p.ai_member.line_user_id: target_line_user_ids.add(p.ai_member.line_user_id)
                else:
                    from members.models import AiMember
                    for m in AiMember.objects.filter(politician=politician).exclude(line_user_id__isnull=True):
                        target_line_user_ids.add(m.line_user_id)

                target_list = list(target_line_user_ids)
                if target_list:
                    for i in range(0, len(target_list), 500):
                        line_bot_api.multicast(target_list[i:i + 500], message)
                    messages.success(request, f'「{event.title}」を {len(target_list)} 名に正式に送信しました！')
            except Exception as e:
                messages.error(request, f'「{event.title}」の送信中にエラーが発生しました: {e}')
        return None # 完了したら元の画面に戻る

    # ==========================================
    # ▼ [第1段階] Runを押した直後の「プレビュー（確認）画面」を作る処理
    # ==========================================
    preview_data = []
    for event in queryset:
        if not event.is_active:
            messages.warning(request, f'「{event.title}」は受付中ではないため除外しました。')
            continue
            
        politician = event.politician
        target_members = set() # AiMemberを入れる箱

        # 誰に送られるか事前にリストアップする
        if event.target_past_event and event.target_past_answer:
            for r in EmergencyResponse.objects.filter(event=event.target_past_event, answer=event.target_past_answer):
                if r.ai_member: target_members.add(r.ai_member)
        elif event.target_group_1 or event.target_group_2 or event.target_group_3 or event.target_note_1 or event.target_note_2 or event.target_note_3:
            from members.models import TenantMemberProfile
            filters = {'politician': politician}
            if event.target_group_1: filters['group_1'] = event.target_group_1
            if event.target_group_2: filters['group_2'] = event.target_group_2
            if event.target_group_3: filters['group_3'] = event.target_group_3
            if event.target_note_1: filters['note_1'] = event.target_note_1
            if event.target_note_2: filters['note_2'] = event.target_note_2
            if event.target_note_3: filters['note_3'] = event.target_note_3
            for p in TenantMemberProfile.objects.filter(**filters).exclude(ai_member__isnull=True):
                if p.ai_member: target_members.add(p.ai_member)
        else:
            from members.models import AiMember
            for m in AiMember.objects.filter(politician=politician).exclude(line_user_id__isnull=True):
                target_members.add(m)

        # プレビュー用の名前リストを作る（最大30人まで表示）
        target_names = [m.real_name or m.line_display_name or "名無し" for m in target_members]
        display_names = ", ".join(target_names[:30])
        if len(target_names) > 30:
            display_names += f" ...他 {len(target_names) - 30} 名"
        if not display_names:
            display_names = "（対象者が見つかりません。条件を見直してください）"

        preview_data.append({
            'event': event,
            'target_count': len(target_members),
            'target_names': display_names,
        })

    if not preview_data: return None

    # 確認画面（HTML）を呼び出して表示する
    context = modeladmin.admin_site.each_context(request)
    context.update({
        'title': '【重要】送信対象者の確認',
        'queryset': queryset,
        'preview_data': preview_data,
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        'action_name': 'broadcast_emergency_message',
    })
    return render(request, 'admin/broadcast_confirm.html', context)

@admin.register(EmergencyEvent)
class EmergencyEventAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'is_active', 'created_at')
    # list_filter = ('politician', 'is_active')
    search_fields = ('title', 'message_body')
    
    # ここで先ほどのインラインパネルを組み込む
    inlines = [EmergencyResponseInline]

    # 【追記】アクションとして登録する
    actions = [broadcast_emergency_message] 

    # ▼▼▼ 新規追加：一般役員からは「所属団体」フィルターだけを隠す ▼▼▼
    def get_list_filter(self, request):
        if request.user.is_superuser:
            return ('politician', 'is_active')
        return ('is_active',) # 一般役員には「受付中かどうか」のフィルターだけ残す

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

@admin.register(CityAdminProfile)
class CityAdminProfileAdmin(admin.ModelAdmin):
    list_display = ('city_name', 'city_code', 'user')

    # ▼▼▼ 新規追加：スーパーユーザー以外はメニューから隠す ▼▼▼
    def has_module_permission(self, request):
        return request.user.is_superuser

# ==========================================
# ▼ 第2フェーズ：行政による「全自治会・横断送信」システム（完全版）
# ==========================================
@admin.action(description="選択した配信を管轄内の全自治会へ横断送信する")
def broadcast_city_emergency_message(modeladmin, request, queryset):
    """市役所担当者が複数自治会をまたいで一斉送信するアクション（確認画面付き）"""

    # ==========================================
    # ▼ [第2段階] 「はい、正式に送信する」が押された後の処理
    # ==========================================
    if 'apply' in request.POST:
        for event in queryset:
            if not event.is_active: continue

            target_politicians = Politician.objects.filter(city_code=event.city_admin.city_code).exclude(line_access_token__isnull=True).exclude(line_access_token__exact='')
            if event.target_district_code:
                target_politicians = target_politicians.filter(district_code__startswith=event.target_district_code)

            total_sent_count = 0
            success_org_count = 0

            message_text = f"【{event.city_admin.city_name}からの重要なお知らせ】\n{event.title}\n\n{event.message_body}"
            if event.attached_file:
                file_url = request.build_absolute_uri(event.attached_file.url)
                message_text += f"\n\n📎 詳細資料（PDF等）:\n{file_url}"

            items = []
            if event.choice_1: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_1[:20], data=f"action=city_emergency&event_id={event.id}&ans=1", display_text=event.choice_1)))
            if event.choice_2: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_2[:20], data=f"action=city_emergency&event_id={event.id}&ans=2", display_text=event.choice_2)))
            if event.choice_3: items.append(QuickReplyButton(action=PostbackAction(label=event.choice_3[:20], data=f"action=city_emergency&event_id={event.id}&ans=3", display_text=event.choice_3)))

            if items: 
                message = TextSendMessage(text=message_text, quick_reply=QuickReply(items=items))
            else: 
                message = TextSendMessage(text=message_text)

            for politician in target_politicians:
                try:
                    line_bot_api = LineBotApi(politician.line_access_token)

                    # 1. まず、この自治会に所属するLINE連携済みユーザーを全員取得（※ここがエラーの原因でした）
                    from members.models import AiMember
                    members_qs = AiMember.objects.filter(politician=politician).exclude(line_user_id__isnull=True)

                    # 2. 行政独自タグでの絞り込み処理
                    if event.target_group_1 or event.target_group_2 or event.target_group_3 or event.target_note_1 or event.target_note_2 or event.target_note_3:
                        profile_filters = {'city_admin': event.city_admin, 'ai_member__politician': politician}
                        if event.target_group_1: profile_filters['group_1'] = event.target_group_1
                        if event.target_group_2: profile_filters['group_2'] = event.target_group_2
                        if event.target_group_3: profile_filters['group_3'] = event.target_group_3
                        if event.target_note_1: profile_filters['note_1'] = event.target_note_1
                        if event.target_note_2: profile_filters['note_2'] = event.target_note_2
                        if event.target_note_3: profile_filters['note_3'] = event.target_note_3

                        matched_profiles = CityMemberProfile.objects.filter(**profile_filters)
                        matched_member_ids = matched_profiles.values_list('ai_member_id', flat=True)
                        members_qs = members_qs.filter(id__in=matched_member_ids)

                    # 3. 最終的に残った人をリスト化して送信
                    target_list = [m.line_user_id for m in members_qs]

                    if target_list:
                        chunk_size = 500
                        for i in range(0, len(target_list), chunk_size):
                            chunk = target_list[i:i + chunk_size]
                            line_bot_api.multicast(chunk, message)

                        total_sent_count += len(target_list)
                        success_org_count += 1

                except Exception as e:
                    messages.error(request, f'【{politician.name}】での送信中にエラーが発生しました: {e}')

            messages.success(request, f'「{event.title}」を {success_org_count}団体、計 {total_sent_count} 名に横断送信しました！')
        return None

    # ==========================================
    # ▼ [第1段階] プレビュー画面の作成（ここも独自タグでの絞り込みに対応させました！）
    # ==========================================
    preview_data = []
    for event in queryset:
        if not event.is_active: continue

        target_politicians = Politician.objects.filter(city_code=event.city_admin.city_code).exclude(line_access_token__isnull=True).exclude(line_access_token__exact='')
        if event.target_district_code:
            target_politicians = target_politicians.filter(district_code__startswith=event.target_district_code)

        from members.models import AiMember
        members_qs = AiMember.objects.filter(politician__in=target_politicians).exclude(line_user_id__isnull=True)

        # プレビューでもタグの絞り込みを計算する
        if event.target_group_1 or event.target_group_2 or event.target_group_3 or event.target_note_1 or event.target_note_2 or event.target_note_3:
            profile_filters = {'city_admin': event.city_admin, 'ai_member__politician__in': target_politicians}
            if event.target_group_1: profile_filters['group_1'] = event.target_group_1
            if event.target_group_2: profile_filters['group_2'] = event.target_group_2
            if event.target_group_3: profile_filters['group_3'] = event.target_group_3
            if event.target_note_1: profile_filters['note_1'] = event.target_note_1
            if event.target_note_2: profile_filters['note_2'] = event.target_note_2
            if event.target_note_3: profile_filters['note_3'] = event.target_note_3

            matched_profiles = CityMemberProfile.objects.filter(**profile_filters)
            matched_member_ids = matched_profiles.values_list('ai_member_id', flat=True)
            members_qs = members_qs.filter(id__in=matched_member_ids)

        org_names = [p.name for p in target_politicians]
        org_display = ", ".join(org_names)
        if not org_display: org_display = "該当する自治会が見つかりません。コードを確認してください。"

        preview_data.append({
            'event': event,
            'target_count': members_qs.count(), # 絞り込まれた正確な人数が出るようになります
            'target_names': f"【送信対象の自治会】\n{org_display}", 
        })

    if not preview_data: return None

    context = modeladmin.admin_site.each_context(request)
    context.update({
        'title': '【重要】市町村・横断送信の最終確認',
        'queryset': queryset,
        'preview_data': preview_data,
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        'action_name': 'broadcast_city_emergency_message',
    })
    return render(request, 'admin/broadcast_confirm.html', context)

class CityEmergencyResponseInline(admin.TabularInline):
    """行政の配信作成画面の中に、住民の回答結果をリアルタイムで表示するパネル"""
    model = CityEmergencyResponse
    extra = 0
    readonly_fields = ('ai_member', 'answer', 'replied_at')
    can_delete = False
    def has_add_permission(self, request, obj):
        return False

@admin.register(CityEmergencyEvent)
class CityEmergencyEventAdmin(admin.ModelAdmin):
    """行政がメッセージを作成・管理するための画面設定"""
    list_display = ('title', 'city_admin', 'target_district_code', 'is_active', 'created_at')
    list_filter = ('city_admin', 'is_active')
    actions = [broadcast_city_emergency_message]
    
    # 画面の中に回答結果のパネルを埋め込む
    inlines = [CityEmergencyResponseInline]

    # 入力画面のレイアウトを整える（選択肢の枠を追加）
    fieldsets = (
        ('基本設定', {
            'fields': ('city_admin', 'title', 'message_body', 'attached_file')
        }),
        ('対象エリアの絞り込み', {
            'fields': ('target_district_code',)
        }),
        ('行政独自タグでの絞り込み（ピンポイント配信）', {
            'fields': ('target_group_1', 'target_group_2', 'target_group_3', 'target_note_1', 'target_note_2', 'target_note_3'),
            'description': '※「市町村・住民プロフィール」で付けたタグと一致する人のみに配信します。'
        }),
        ('回答ボタン（アンケート・安否確認）', {
            'fields': ('choice_1', 'choice_2', 'choice_3'),
            'description': '入力すると、LINEのメッセージの下にタップできる回答ボタンが表示されます。'
        }),
        ('ステータス', {
            'fields': ('is_active',)
        }),
    )

    def get_queryset(self, request):
        """【防衛策】市役所担当者は、自分の市役所が作った配信だけを見れる"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(city_admin__user=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """【防衛策】作成者を自分（市役所）に固定する"""
        if db_field.name == "city_admin" and not request.user.is_superuser:
            kwargs["queryset"] = CityAdminProfile.objects.filter(user=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # ▼▼▼ 新規追加：スーパーユーザー以外はメニューから隠す ▼▼▼
    def has_module_permission(self, request):
        return request.user.is_superuser

# ==========================================
# ▼ 第2フェーズ：行政専用の「住民タグ付け」管理画面（個人情報保護対応）
# ==========================================
@admin.register(CityMemberProfile)
class CityMemberProfileAdmin(admin.ModelAdmin):
    """市役所担当者が住民に独自タグを付ける画面。個人情報保護のため表示を極限まで絞る。"""
    list_display = ('get_org_name', 'get_address', 'get_real_name', 'group_1', 'note_1')
    list_filter = ('ai_member__politician', 'group_1', 'group_2')
    search_fields = ('ai_member__real_name', 'ai_member__address')
    
    # 【重要】数万人の住民から探せるように、虫眼鏡マークの検索窓（ポップアップ）にする
    raw_id_fields = ('ai_member',) 

    fieldsets = (
        ('基本情報', {
            'fields': ('city_admin', 'ai_member'),
        }),
        ('行政独自タグ（配信の絞り込み用）', {
            'fields': ('group_1', 'group_2', 'group_3', 'note_1', 'note_2', 'note_3'),
            'description': '※ここに入力したタグは、横断送信時の「絞り込み条件」として利用できます。'
        }),
    )

    def get_org_name(self, obj):
        return obj.ai_member.politician.name
    get_org_name.short_description = '団体名（自治会）'

    def get_address(self, obj):
        return obj.ai_member.address or "未登録"
    get_address.short_description = '班名・部屋番号'

    def get_real_name(self, obj):
        return obj.ai_member.real_name or "未登録"
    get_real_name.short_description = '氏名'

    def get_queryset(self, request):
        """【防衛策】自分の管轄のプロフィールしか見られない"""
        qs = super().get_queryset(request)
        if request.user.is_superuser: return qs
        return qs.filter(city_admin__user=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """【防衛策】作成者を自分（市役所）に固定する"""
        if db_field.name == "city_admin" and not request.user.is_superuser:
            kwargs["queryset"] = CityAdminProfile.objects.filter(user=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
        
    # ▼▼▼ 新規追加：スーパーユーザー以外はメニューから隠す ▼▼▼
    def has_module_permission(self, request):
        return request.user.is_superuser

@admin.register(PublicPageConfig)
class PublicPageConfigAdmin(admin.ModelAdmin):
    list_display = ('politician', 'is_public', 'updated_at')
    list_filter = ('is_public',)
    search_fields = ('politician__name',)

    # 🛡️ 医療圏とおくやみエリア（市町村）の両方を左右のボックスUIにする
    filter_horizontal = ('target_medical_areas', 'target_condolence_areas') 

    readonly_fields = ('qr_code_display',)    
    
    fieldsets = (
        ('基本設定', {
            'fields': ('politician', 'is_public', 'qr_code_display')
        }),
        ('デザイン・レイアウト', {
            'fields': ('main_visual', 'accent_color', 'welcome_text')
        }),
        ('表示・配信機能の制御', {
            # 🔴 ここに target_condolence_areas を追加する
            'fields': (
                'show_announcements', 
                'show_events', 
                'show_library', 
                'target_medical_areas',
                'target_condolence_areas' 
            ),
            'description': '※各機能の表示スイッチ、およびこの自治会ページに表示する「医療圏」と「おくやみ情報の対象市町村」を選択してください。'
        }),
    )

    def qr_code_display(self, obj):
        # 設定が保存されており、かつ公開状態の場合のみQRを表示
        if obj.pk and obj.is_public and obj.politician.slug:
            target_url = f"https://jichidantai.jp/p/{obj.politician.slug}/"
            api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={target_url}"
            
            return format_html(
                '<img src="{}" width="150" height="150" style="border: 1px solid #ccc; padding: 5px; background: white;"/><br>'
                '<br><a href="{}" target="_blank" style="display:inline-block; padding: 5px 10px; background: #007bff; color: white; text-decoration: none; border-radius: 3px;">📥 QR画像をダウンロード</a>'
                '<p style="color: #666; margin-top: 5px;">※この画像を右クリックで保存し、回覧板や公民館のポスターに印刷してご活用ください。</p>',
                api_url, api_url
            )
        return "ページを「公開」にして一度保存すると、ここにポスター印刷用のQRコードが自動生成されます。"
    
    qr_code_display.short_description = "回覧板・ポスター用QRコード"    
    
class BroadcastMessageAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'is_sent', 'sent_at', 'target_count')
    list_filter = ('politician', 'is_sent')
    search_fields = ('title', 'message_text')

    actions = ['send_broadcast_action']
    
    # 🛡️ 防衛的設計: 送信済みのメッセージは改ざん（証拠隠滅）できないように読取専用にする
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_sent:
            return ['politician', 'title', 'message_text', 'is_sent', 'sent_at', 'target_count']
        return ['is_sent', 'sent_at', 'target_count'] # 新規作成時はステータス類を触らせない

    # 🛡️ 運営側の防衛的視点: 送信前の「確認画面」と「500人分割送信」のロジック
    @admin.action(description='🚀 選択したメッセージをLINEで一斉送信する')
    def send_broadcast_action(self, request, queryset):
        # 1. 二重送信ブロック（送信済みのものは弾く）
        if queryset.filter(is_sent=True).exists():
            self.message_user(request, "エラー：既に送信済みのメッセージが含まれています。未送信のものだけを選択してください。", level=messages.ERROR)
            return

        # 2. 「はい、送信する（apply）」が押された場合の本処理
        if request.POST.get('apply'):
            success_count = 0
            for msg in queryset:
                politician = msg.politician
                if not politician.line_access_token:
                    continue
                
                line_bot_api = LineBotApi(politician.line_access_token)
                # 対象自治会の住民を取得（LINE IDが登録されている人のみ）
                members = AiMember.objects.filter(politician=politician).exclude(line_user_id__isnull=True).exclude(line_user_id__exact='')
                target_user_ids = [m.line_user_id for m in members]
                
                if not target_user_ids:
                    continue
                
                # 🛡️ API制限対策: 500人ずつに分割（Chunk）してMulticast送信
                chunk_size = 500
                sent_count = 0
                for i in range(0, len(target_user_ids), chunk_size):
                    chunk = target_user_ids[i:i + chunk_size]
                    try:
                        line_bot_api.multicast(chunk, TextSendMessage(text=msg.message_text))
                        sent_count += len(chunk)
                    except LineBotApiError as e:
                        print(f"LINE Broadcast Error: {e}")
                
                # データベースのステータスを「送信済」にロック
                msg.is_sent = True
                msg.sent_at = timezone.now()
                msg.target_count = sent_count
                msg.save()
                success_count += 1
                
            self.message_user(request, f"{success_count}件のメッセージを正式に配信しました。", level=messages.SUCCESS)
            return

        # 3. まだ「apply」が押されていない場合は、確認画面を表示する
        preview_data = []
        for msg in queryset:
            members = AiMember.objects.filter(politician=msg.politician)
            # 誰に送るのかを抜粋して表示（例: 坂井康夫、〇〇、... など計50名）
            target_names = "、".join([m.real_name or m.line_display_name or "未設定" for m in members[:10]])
            if members.count() > 10:
                target_names += f" ...など計{members.count()}名"
                
            preview_data.append({
                'event': msg,  # 以前作成した broadcast_confirm.html の変数名(event_data.event.title)に合わせる
                'target_count': members.count(),
                'target_names': target_names,
            })
            
        context = {
            **self.admin_site.each_context(request),
            'title': '⚠️ LINE一斉送信の最終確認',
            'preview_data': preview_data,
            'queryset': queryset,
            'action_name': 'send_broadcast_action',
        }
        return render(request, 'admin/broadcast_confirm.html', context)

# 1. 市町村マスタの登録
@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    list_display = ('prefecture', 'name')
    search_fields = ('name',)

# 2. 葬祭場マスタの登録
@admin.register(FuneralHall)
class FuneralHallAdmin(admin.ModelAdmin):
    list_display = ('name', 'municipality', 'phone')
    list_filter = ('municipality',)
    search_fields = ('name', 'address')

    # 🛡️ 変更点: 医療機関マスタと同じ地図連携（緯度経度の自動入力）を追加
    fields = ('name', 'municipality', 'address', 'phone', ('latitude', 'longitude'), 'map_canvas')
    readonly_fields = ('map_canvas',)

    def map_canvas(self, obj):
        return mark_safe(
            '<div id="admin-map" style="height: 400px; width: 100%; margin-bottom: 20px; border: 1px solid #ccc;"></div>'
            '<p class="help">地図をクリックするとピンが移動し、座標が自動入力されます。</p>'
        )

    class Media:
        js = (
            'js/admin_map.js',
            f'https://maps.googleapis.com/maps/api/js?key={settings.GOOGLE_MAPS_API_KEY}&callback=initMap',
        )

# 3. おくやみ情報の登録（管理者の一元入力用）
@admin.register(Condolence)
class CondolenceAdmin(admin.ModelAdmin):
    list_display = ('deceased_name', 'funeral_hall', 'funeral_datetime')
    list_filter = ('funeral_hall__municipality', 'ceremony_type') # 市町村で絞り込み可能
    search_fields = ('deceased_name', 'deceased_address')

# ==========================================
# ▼ 新規追加：AI利用枠管理の表示設定
# ==========================================
@admin.register(TenantLLMQuota)
class TenantLLMQuotaAdmin(admin.ModelAdmin):
    # 一覧画面に表示する項目
    list_display = ('politician', 'monthly_limit', 'current_month_usage', 'last_reset_date')
    list_filter = ('politician',)
    search_fields = ('politician__name',)
    
    # 🛡️ 運営側の防衛的視点:
    # 運用開始後は、役員が誤って利用回数（current_month_usage）を書き換えて
    # 制限を突破してしまわないよう、読み取り専用（readonly_fields）にするのが安全ですが、
    # 現在はテスト稼働中のため手動編集を開放しておきます。
    # readonly_fields = ('current_month_usage', 'last_reset_date')
    