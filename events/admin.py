import csv
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils.html import format_html
from .models import Event, EventPhoto, Announcement, Survey, SurveyResponse

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # 一覧画面で表示する項目
    list_display = ('title','politician', 'start_time', 'location', 'is_active')
    list_filter = ('politician', 'is_active')
    search_fields = ('title', 'description')
    # 日付の新しい順に並べる
    ordering = ('-start_time',)

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'politician', 'created_at', 'is_active')
    list_filter = ('politician', 'is_active', 'created_at')
    search_fields = ('title', 'content')    

@admin.register(EventPhoto)
class EventPhotoAdmin(admin.ModelAdmin):
    list_display = ('title', 'image', 'uploaded_at')

@admin.register(Survey)
class SurveyAdmin(admin.ModelAdmin):
    # 🔴 list_display に作成したボタン（export_csv_button）を追加します
    list_display = ('title', 'politician', 'deadline', 'is_active', 'export_csv_button')
    list_filter = ('politician', 'is_active')
    search_fields = ('title',)

    # 🛡️ 運営側の防衛的視点 1: 管理画面のURLを拡張し、CSVダウンロード用の専用裏ルートを作成
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:survey_id>/export-csv/', self.admin_site.admin_view(self.export_csv), name='survey-export-csv'),
        ]
        return custom_urls + urls

    # 🛡️ 運営側の防衛的視点 2: 役員が直感的に押せる専用ボタンのUI（HTML）を生成
    def export_csv_button(self, obj):
        return format_html(
            '<a class="button" style="background-color: #28a745; color: white; padding: 5px 10px; border-radius: 3px; font-weight: bold;" href="{}">📥 Excel(CSV)出力</a>',
            f"{obj.id}/export-csv/"
        )
    export_csv_button.short_description = '回答データ一括出力'

    # 🛡️ 運営側の防衛的視点 3: Excelの文字化けを防ぐBOM付きUTF-8でのデータ出力ロジック
    def export_csv(self, request, survey_id):
        survey = self.get_object(request, survey_id)
        responses = survey.responses.all().order_by('submitted_at')

        # 'utf-8-sig' を指定することで、WindowsのExcelで直接開いても文字化けしないBOM付きCSVになります
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="survey_results_{survey_id}.csv"'

        writer = csv.writer(response)
        # ヘッダー行の作成（そのまま議事録の添付資料として使える粒度にする）
        writer.writerow(['回答日時', '回答者名', '出欠・賛否', 'ご意見・自由記述'])

        # データ行の書き込み
        for r in responses:
            # 日時を日本時間で読みやすいフォーマットに変換
            local_time = r.submitted_at.astimezone().strftime('%Y/%m/%d %H:%M')
            writer.writerow([
                local_time,
                r.respondent_name,
                r.attendance,
                r.comment
            ])
            
        return response

@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ('survey', 'respondent_name', 'attendance', 'submitted_at')
    list_filter = ('survey__politician', 'survey', 'attendance')
    search_fields = ('respondent_name', 'comment')
    readonly_fields = ('session_key', 'ip_address', 'submitted_at') # 追跡データは改ざん防止のため読取専用
