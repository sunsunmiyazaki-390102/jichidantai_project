"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.shortcuts import redirect  # 🔴 追加：リダイレクト（転送）用の部品
from django.conf import settings
from django.conf.urls.static import static
from bot import views as bot_views
from events import views as events_views

# ★追加2：簡単な表示機能を作る（LIFFルーター兼用にアップデート）
def index(request):
    # 🛡️ 防衛的視点：LIFFからの動的ルーティングパラメータをキャッチ
    liff_state = request.GET.get('liff.state')
    
    # liff.state が存在し、かつ安全な内部パス（/から始まる）場合のみ転送
    if liff_state and liff_state.startswith('/'):
        return redirect(liff_state)
        
    # LIFF経由ではない、通常のルートアクセスの場合はトップページを表示
    return HttpResponse("<h1>Hello Django!</h1><p>自治会のローカル環境は正常です。</p>")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('library/', include('library.urls')),
    path('bot/', include('bot.urls')),
    path('', index), # ★追加3：空っぽ（トップページ）の行き先を指定
    # 新規追加：自治会ごとの公開ページ用URL (p = page/public の略)
    path('p/<slug:slug>/', bot_views.public_tenant_page, name='public_tenant_page'),
    # 新規追加：議事録作成サポート画面
    path('minutes-support/', bot_views.minutes_support_page, name='minutes_support_page'),
    path('survey/<int:survey_id>/', events_views.survey_detail, name='survey_detail'),
    path('accounting/', include('accounting.urls')),
    path('reservations/', include('reservations.urls')),        
]

# アップロードされたメディアファイル（PDFや画像）を表示するための設定
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    