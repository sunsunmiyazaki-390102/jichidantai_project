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
from django.urls import path
from django.urls import path, include
from django.http import HttpResponse # ★追加1：画面に文字を出す部品

# ★追加2：簡単な表示機能を作る
def index(request):
    return HttpResponse("<h1>Hello Django!</h1><p>自治会のローカル環境は正常です。</p>")

urlpatterns = [
    path('admin/', admin.site.urls),
    # botアプリのurls.pyを読み込む設定を追加
    path('bot/', include('bot.urls')),
    path('', index), # ★追加3：空っぽ（トップページ）の行き先を指定
]
