from django.urls import path
from . import views

app_name = 'reservations'

urlpatterns = [
    # 住民向けカレンダー画面
    path('<slug:slug>/', views.calendar_view, name='calendar'),
    # カレンダーの裏側で動くデータ提供用API
    path('<slug:slug>/api/events/', views.events_api, name='events_api'),
]
