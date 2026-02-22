from django.contrib import admin
from .models import AiMember

@admin.register(AiMember)
class AiMemberAdmin(admin.ModelAdmin):
    list_display = ('line_user_id', 'real_name', 'current_level', 'is_approved', 'created_at')
    list_editable = ('is_approved', 'current_level') # 一覧画面でそのまま編集可能に
    search_fields = ('real_name', 'line_user_id', 'address')
    list_filter = ('current_level', 'is_approved')

# members/admin.py の抜粋例
def generate_lesson_action(modeladmin, request, queryset):
    # Geminiを呼び出して教材を作成し、対象ユーザーにLINE送信するロジック
    # (ここは後ほど ai_engine/services.py と連携させます)
    pass

generate_lesson_action.short_description = "選択したメンバーにGemini教材を生成・配信"
    