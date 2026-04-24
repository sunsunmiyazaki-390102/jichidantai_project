from django.shortcuts import render
from .models import LibraryDocument
from django.core.paginator import Paginator

def library_list(request):
    """
    住民向けの資料一覧画面（フロントエンド）
    """
    # 🛡️ 運営側の防衛的視点: 
    # 本番運用（LINE等との連携時）では、ここで「アクセスしてきた住民の自治会ID」を取得し、
    # その自治会の資料だけを出すようにシビアなフィルタリング（テナント分離）を行います。
    # 
    # ※ 現在はフロントエンド（画面）の表示テストのため、
    # ひとまず「全住民公開 (PUBLIC)」に設定されている資料をすべて表示する仕様にしています。
    
    documents = LibraryDocument.active_objects.filter(
        access_level='PUBLIC'
    ).order_by('-fiscal_year', '-created_at')

    # 大量データ対策: 1ページ20件のページネーション
    paginator = Paginator(documents, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'library/document_list.html', {
        'page_obj': page_obj,
    })