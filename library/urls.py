from django.urls import path
from . import views

# アプリの名前空間を設定（防衛的設計：URLの重複を防ぐ）
app_name = 'library'

urlpatterns = [
    # https://jichidantai.jp/library/
    path('', views.library_list, name='document_list'),
]