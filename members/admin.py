from django.contrib import admin
from import_export import resources, fields
from import_export.admin import ImportExportModelAdmin
from import_export.widgets import ForeignKeyWidget

from .models import AiMember, TenantMemberProfile
from bot.models import Politician

# ==========================================
# 1. AiMember (LINEアカウント) の管理画面
# ==========================================
def generate_lesson_action(modeladmin, request, queryset):
    # Geminiを呼び出して教材を作成し、対象ユーザーにLINE送信するロジック
    # (ここは後ほど ai_engine/services.py と連携させます)
    pass
generate_lesson_action.short_description = "選択したメンバーにGemini教材を生成・配信"

@admin.register(AiMember)
class AiMemberAdmin(admin.ModelAdmin):
    list_display = ('line_user_id', 'real_name', 'current_level', 'is_approved', 'created_at', 'line_display_name')
    list_editable = ('is_approved', 'current_level') # 一覧画面でそのまま編集可能に
    search_fields = ('real_name', 'line_user_id', 'address')
    list_filter = ('current_level', 'is_approved', 'politician')
    actions = [generate_lesson_action]

    def get_queryset(self, request):
        """【防衛的措置】LINEアカウント一覧のテナント分離"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # 一般管理者は自団体のLINEアカウントしか見られない
        return qs.filter(politician__admin_users=request.user).distinct()

# ==========================================
# 2. 🛡️ 運営側の防衛的措置：テナント分離型CSVインポート基盤
# ==========================================
class TenantMemberProfileResource(resources.ModelResource):
    # 【修正】変数名を models.py に合わせて 'ai_member' に統一
    ai_member = fields.Field(
        column_name='LINE_ID',
        attribute='ai_member',
        widget=ForeignKeyWidget(AiMember, 'line_user_id')
    )
    official_name = fields.Field(attribute='official_name', column_name='氏名')
    group_2 = fields.Field(attribute='group_2', column_name='班名')
    
    # 必須項目「管理番号」もフィールドとして定義しておく
    management_id = fields.Field(attribute='management_id', column_name='管理番号')

    class Meta:
        model = TenantMemberProfile
        # 【修正】判定基準も 'ai_member' に変更
        import_id_fields = ('ai_member',)
        fields = ('ai_member', 'official_name', 'group_2', 'management_id')
        skip_unchanged = True

    def __init__(self, **kwargs):
        # kwargsの中から 'request' を取り出し、親クラスの __init__ には渡さない
        self.request = kwargs.pop('request', None)
        super().__init__(**kwargs)

    def before_import_row(self, row, **kwargs):
        """【防衛策】CSVの1行が保存される『直前』に介入するロジック"""
        line_user_id = row.get('LINE_ID')
        if not line_user_id:
            return

        # 1. ログイン中の一般管理者が担当する自治会を特定
        if self.request and not self.request.user.is_superuser:
            tenant = Politician.objects.filter(admin_users=self.request.user).first()
            if not tenant:
                raise ValueError("操作エラー：あなたの管理アカウントに紐づく自治会が存在しません。")
        else:
            raise ValueError("防衛的措置：インポートの事故を防ぐため、CSVインポートは必ず『各自治会の管理者アカウント』でログインして実行してください。")

        # 2. AiMember（LINEアカウント）が未登録なら裏で自動生成する
        ai_member_obj, created = AiMember.objects.get_or_create(
            line_user_id=line_user_id,
            defaults={'politician': tenant}
        )

        # 3. テナント越境エラーの完全遮断
        if ai_member_obj.politician and ai_member_obj.politician != tenant:
            raise ValueError(f"重大エラー：LINE ID({line_user_id}) は既に他団体に所属しているためインポートを遮断しました。")

        # 4. 【シビアな防衛策】必須項目「管理番号」がCSVに無い場合の自動補完
        # データベースエラーでインポートが止まるのを防ぐため、LINE_IDの先頭8文字を使って仮の管理番号を自動生成する
        if not row.get('管理番号'):
            row['管理番号'] = f"auto_{line_user_id[:8]}"

    def before_save_instance(self, instance, row, **kwargs):
        """プロフィール本体が保存される直前に、所属団体を強制上書き"""
        if self.request and not self.request.user.is_superuser:
            tenant = Politician.objects.filter(admin_users=self.request.user).first()
            instance.politician = tenant
            
# ==========================================
# 3. 名簿プロフィール (TenantMemberProfile) の管理画面
# ==========================================
@admin.register(TenantMemberProfile)
class TenantMemberProfileAdmin(ImportExportModelAdmin):
    resource_class = TenantMemberProfileResource
    
    # 【修正】list_display も 'ai_member' に変更し復活
    list_display = ('management_id', 'official_name', 'politician', 'ai_member', 'group_2')
    search_fields = ('official_name', 'management_id')
    list_filter = ('politician',)

    def get_import_resource_kwargs(self, request, *args, **kwargs):
        kwargs = super().get_import_resource_kwargs(request, *args, **kwargs)
        kwargs.update({"request": request})
        return kwargs

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(politician__admin_users=request.user).distinct()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # スーパーユーザー以外（一般管理者）の場合のみ制限をかける
        if not request.user.is_superuser:
            from bot.models import Politician # 念のためインポート
            tenant = Politician.objects.filter(admin_users=request.user).first()
            
            if tenant:
                # ①「所属団体」のプルダウンを自団体のみに制限（他団体を間違えて選ばないように）
                if 'politician' in form.base_fields:
                    form.base_fields['politician'].queryset = form.base_fields['politician'].queryset.filter(id=tenant.id)
                
                # ②「紐づくLINEアカウント」のプルダウンを、自団体のLINEユーザーのみに制限
                if 'ai_member' in form.base_fields:
                    form.base_fields['ai_member'].queryset = form.base_fields['ai_member'].queryset.filter(politician=tenant)
                       
        if obj and obj.politician:
            if 'group_1' in form.base_fields:
                form.base_fields['group_1'].label = obj.politician.label_group_1
            if 'group_2' in form.base_fields:
                form.base_fields['group_2'].label = obj.politician.label_group_2
            if 'group_3' in form.base_fields:
                form.base_fields['group_3'].label = obj.politician.label_group_3
            if 'note_1' in form.base_fields:
                form.base_fields['note_1'].label = obj.politician.label_note_1
            if 'note_2' in form.base_fields:
                form.base_fields['note_2'].label = obj.politician.label_note_2
            if 'note_3' in form.base_fields:
                form.base_fields['note_3'].label = obj.politician.label_note_3
        return form
