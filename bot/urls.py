from django.urls import path
from . import views
from bot import views

urlpatterns = [
    # 最終的なURLは https://aikouenkai.jp/bot/callback/ になります
    # path('callback/', views.callback, name='callback'),
    path('webhook/<slug:politician_slug>/', views.callback, name='callback'),
]