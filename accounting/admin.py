from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import FiscalYear, AccountCategory, Transaction, Budget

# 🛡️ 新規追加：年度画面に埋め込むための予算インライン設定
class BudgetInline(admin.TabularInline):
    model = Budget
    extra = 1  # 新規追加用の空行を1行用意

@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'politician', 'start_date', 'end_date', 'is_locked', 'report_link')
    list_filter = ('politician', 'is_locked')
    
    # 🔴 ここを追加：会計年度の編集画面の「下部」に予算入力欄を合体させる
    inlines = [BudgetInline] 

    @admin.display(description="総会資料")
    def report_link(self, obj):
        url = reverse('accounting:assembly_report', args=[obj.id])
        return format_html(
            '<a class="button" href="{}" target="_blank" style="background-color: #17a2b8; color: white; padding: 5px 10px; border-radius: 3px; font-weight: bold;">🖨️ 資料生成</a>',
            url
        )

@admin.register(AccountCategory)
class AccountCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'politician', 'category_type', 'order', 'is_active')
    list_filter = ('politician', 'category_type', 'is_active')
    list_editable = ('order', 'is_active')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'politician', 'fiscal_year', 'category', 'amount', 'is_cancelled')
    list_filter = ('politician', 'fiscal_year', 'category__category_type', 'is_cancelled')
    search_fields = ('description', 'cancelled_reason')
    date_hierarchy = 'date'
    
    # 🛡️ 取消済みの場合は金額などを赤字にするなどの工夫が可能
    fieldsets = (
        ('基本情報', {
            'fields': ('politician', 'fiscal_year', 'date', 'category', 'amount', 'description', 'receipt_image')
        }),
        ('赤黒処理（データ修正時）', {
            'fields': ('is_cancelled', 'cancelled_reason'),
            'description': '※入力ミスを修正する場合は、この伝票を「取消済」にし、正しい内容で新しい伝票を作成してください。'
        }),
    )

    # 🛡️ 運営側の防衛的視点：管理画面のUIからも「削除ボタン」を完全に消し去る
    def has_delete_permission(self, request, obj=None):
        return False