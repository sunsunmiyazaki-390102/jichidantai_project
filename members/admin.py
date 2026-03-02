from django.contrib import admin
from .models import AiMember, TenantMemberProfile
@admin.register(AiMember)
class AiMemberAdmin(admin.ModelAdmin):
    list_display = ('line_user_id', 'real_name', 'current_level', 'is_approved', 'created_at', 'line_display_name')
    list_editable = ('is_approved', 'current_level') # 一覧画面でそのまま編集可能に
    search_fields = ('real_name', 'line_user_id', 'address')
    list_filter = ('current_level', 'is_approved')

# members/admin.py の抜粋例
def generate_lesson_action(modeladmin, request, queryset):
    # Geminiを呼び出して教材を作成し、対象ユーザーにLINE送信するロジック
    # (ここは後ほど ai_engine/services.py と連携させます)
    pass

generate_lesson_action.short_description = "選択したメンバーにGemini教材を生成・配信"

@admin.register(TenantMemberProfile)
class TenantMemberProfileAdmin(admin.ModelAdmin):
    list_display = ('management_id', 'official_name', 'politician')
    search_fields = ('official_name', 'management_id')
    list_filter = ('politician',)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # 登録済みのデータで、かつ所属団体が紐づいている場合のみラベルを上書きする
        if obj and obj.politician:
            form.base_fields['group_1'].label = obj.politician.label_group_1
            form.base_fields['group_2'].label = obj.politician.label_group_2
            form.base_fields['group_3'].label = obj.politician.label_group_3
            form.base_fields['note_1'].label = obj.politician.label_note_1
            form.base_fields['note_2'].label = obj.politician.label_note_2
            form.base_fields['note_3'].label = obj.politician.label_note_3
        return form
        