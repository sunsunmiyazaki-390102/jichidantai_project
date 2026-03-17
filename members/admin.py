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
    ai_member = fields.Field(
        column_name='LINE_ID',
        attribute='ai_member',
        widget=ForeignKeyWidget(AiMember, 'line_user_id')
    )
    # ▼▼▼ Excelに出力・入力したい列をモデルに合わせて定義します ▼▼▼
    management_id = fields.Field(attribute='management_id', column_name='管理番号')
    official_name = fields.Field(attribute='official_name', column_name='氏名')
    
    # 住所・世帯関連
    official_address = fields.Field(attribute='official_address', column_name='住所')
    birth_date = fields.Field(attribute='birth_date', column_name='生年月日')
    head_of_household = fields.Field(attribute='head_of_household', column_name='世帯主名')
    relationship = fields.Field(attribute='relationship', column_name='世帯主との続柄')
    
    # グループ関連
    group_1 = fields.Field(attribute='group_1', column_name='グループ1')
    group_2 = fields.Field(attribute='group_2', column_name='グループ2（班名）')
    group_3 = fields.Field(attribute='group_3', column_name='グループ3')
    
    # 備考関連
    note_1 = fields.Field(attribute='note_1', column_name='備考1')
    note_2 = fields.Field(attribute='note_2', column_name='備考2')
    note_3 = fields.Field(attribute='note_3', column_name='備考3')
    # ▲▲▲ ここまで ▲▲▲

    class Meta:
        model = TenantMemberProfile
        import_id_fields = ('ai_member',)
        
        # ▼▼▼ Excelとして扱うフィールド（出力する順番）を列挙します ▼▼▼
        fields = (
            'ai_member', 'management_id', 'official_name', 
            'official_address', 'birth_date', 'head_of_household', 'relationship',
            'group_1', 'group_2', 'group_3', 
            'note_1', 'note_2', 'note_3'
        )
        
        # エクスポート時の「列の並び順」を指定します
        export_order = fields
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
        tenant = None # 初期化
        if self.request and not self.request.user.is_superuser:
            tenant = Politician.objects.filter(admin_users=self.request.user).first()
            if not tenant:
                raise ValueError("操作エラー：あなたの管理アカウントに紐づく自治会が存在しません。")
        elif self.request and self.request.user.is_superuser:
            # スーパーユーザーの場合は、CSVから直接インポートできるようにテナントチェックを少し緩める
            pass
        else:
            raise ValueError("防衛的措置：インポートの事故を防ぐため、CSVインポートは必ず『各自治会の管理者アカウント』でログインして実行してください。")

        # 2. AiMember（LINEアカウント）が未登録なら裏で自動生成する
        if tenant:
            ai_member_obj, created = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={'politician': tenant}
            )

            # 3. テナント越境エラーの完全遮断
            if ai_member_obj.politician and ai_member_obj.politician != tenant:
                raise ValueError(f"重大エラー：LINE ID({line_user_id}) は既に他団体に所属しているためインポートを遮断しました。")

        # 4. 【シビアな防衛策】必須項目「管理番号」がCSVに無い場合の自動補完
        if not row.get('管理番号'):
            row['管理番号'] = f"auto_{line_user_id[:8]}"

        # ▼▼▼ 新規追加：エクセルの「空白セル」が日付エラーを起こすのを防ぐ ▼▼▼
        raw_date = row.get('生年月日')
        if raw_date == "" or str(raw_date).strip() == "":
            row['生年月日'] = None

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
        from django.db.models import Q # ← ★新規追加：複雑な「OR（または）」条件を作るための魔法の部品

        # ==========================================
        # ▼ 一般管理者（自治会役員）向けのプルダウン制限
        # ==========================================
        if not request.user.is_superuser:
            from bot.models import Politician # 念のためインポート
            tenant = Politician.objects.filter(admin_users=request.user).first()
            
            if tenant:
                # ①「所属団体」のプルダウンを自団体のみに制限
                if 'politician' in form.base_fields:
                    form.base_fields['politician'].queryset = form.base_fields['politician'].queryset.filter(id=tenant.id)
                
                # ②「紐づくLINEアカウント」のプルダウンから作成済みを除外！
                if 'ai_member' in form.base_fields:
                    if obj and obj.ai_member:
                        # 【編集画面を開いた時】未登録の人 ＋「今この名簿に紐づいている本人」を表示
                        form.base_fields['ai_member'].queryset = form.base_fields['ai_member'].queryset.filter(
                            Q(politician=tenant) & (Q(profile__isnull=True) | Q(id=obj.ai_member.id))
                        )
                    else:
                        # 【新規追加画面を開いた時】まだ名簿が無い（未登録の）人だけをスッキリ表示
                        form.base_fields['ai_member'].queryset = form.base_fields['ai_member'].queryset.filter(
                            politician=tenant, profile__isnull=True
                        )

        # ==========================================
        # ▼ スーパーユーザー（システム管理者）向けのプルダウン制限
        # ==========================================
        else:
            if 'ai_member' in form.base_fields:
                if obj and obj.ai_member:
                    form.base_fields['ai_member'].queryset = form.base_fields['ai_member'].queryset.filter(
                        Q(profile__isnull=True) | Q(id=obj.ai_member.id)
                    )
                else:
                    form.base_fields['ai_member'].queryset = form.base_fields['ai_member'].queryset.filter(profile__isnull=True)

        # ==========================================
        # ▼ 各団体のカスタムラベル（グループ名など）の適用
        # ==========================================
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
