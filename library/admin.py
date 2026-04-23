from django.contrib import admin
from .models import LibraryDocument

@admin.register(LibraryDocument)
class LibraryDocumentAdmin(admin.ModelAdmin):
    # 運営側の防衛的視点: 管理者が「どの自治会の、誰向けの、いつの資料か」を一目で把握・検索できる強力なリスト表示
    list_display = ('title', 'politician', 'fiscal_year', 'category', 'access_level', 'is_deleted', 'updated_at')
    
    # 右側に強力な絞り込みフィルターを設置（テナント間でのデータ探しを容易にする）
    list_filter = ('politician', 'fiscal_year', 'category', 'access_level', 'is_deleted')
    
    # タイトルでのテキスト検索を有効化
    search_fields = ('title',)
    