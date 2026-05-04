from django.urls import path
from . import views

app_name = 'accounting'

urlpatterns = [
    # 総会資料プレビュー画面へのURL
    path('report/<int:year_id>/', views.assembly_report_view, name='assembly_report'),
]
