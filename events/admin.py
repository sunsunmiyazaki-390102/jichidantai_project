import csv
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils.safestring import mark_safe
from django.conf import settings
from .models import Event, EventPhoto, Announcement, Survey, SurveyResponse, MedicalInstitution, HolidayDutySchedule, MedicalArea

@admin.register(MedicalArea)
class MedicalAreaAdmin(admin.ModelAdmin):
    """医療圏マスタの管理画面"""
    list_display = ('name', 'order')
    list_editable = ('order',)
    search_fields = ('name',)

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

# 🛡️ 運営側の防衛的視点: Excelで開いた際の文字化けを完全防止するため「utf-8-sig」でレスポンスを返す
@admin.action(description='選択した医療機関をCSVでバックアップ出力')
def export_medical_institutions_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="medical_institutions_backup.csv"'
    
    writer = csv.writer(response)
    # 抽出するヘッダー（将来のインポート時にそのまま使えるフォーマット）
    writer.writerow(['病院名', '住所', '電話番号', '公式サイトURL', '緯度', '経度', '有効フラグ'])
    
    for obj in queryset:
        writer.writerow([
            obj.name,
            obj.address,
            obj.phone,
            obj.website_url if obj.website_url else '',
            obj.latitude if obj.latitude else '',
            obj.longitude if obj.longitude else '',
            '1' if obj.is_active else '0'
        ])
    return response

@admin.register(MedicalInstitution)
class MedicalInstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'latitude', 'longitude', 'is_active')
    search_fields = ('name', 'phone', 'address')
    fields = ('name', 'address', 'phone', 'website_url', ('latitude', 'longitude'), 'map_canvas', 'is_active')
    readonly_fields = ('map_canvas',)
    
    # ▼ 新規追加: 作成したアクションを管理画面に登録
    actions = [export_medical_institutions_csv]

    def map_canvas(self, obj):
        return mark_safe(
            '<div id="admin-map" style="height: 400px; width: 100%; margin-bottom: 20px; border: 1px solid #ccc;"></div>'
            '<p class="help">地図をクリックするとピンが移動し、座標が自動入力されます。</p>'
        )

    class Media:
        js = (
            'js/admin_map.js',
            f'https://maps.googleapis.com/maps/api/js?key={settings.GOOGLE_MAPS_API_KEY}&callback=initMap',
        )

@admin.register(HolidayDutySchedule)
class HolidayDutyScheduleAdmin(admin.ModelAdmin):
    """当番医スケジュールの管理画面"""
    # 修正: department を get_department (マスタからの呼び出し) に変更
    list_display = ('date', 'get_institution_name', 'get_department', 'get_institution_phone', 'note')
    
    # 修正: マスタ側の department を使って絞り込みを行う
    list_filter = ('date', 'institution__department')
    
    autocomplete_fields = ['institution'] 
    date_hierarchy = 'date'
    
    # 修正: department はマスタの管轄になったため、ここでの直接編集(list_editable)から外す
    list_editable = ('note',)

    def get_institution_name(self, obj):
        return obj.institution.name
    get_institution_name.short_description = '当番医院'

    # 新規追加: マスタ側から診療科目を引っ張ってきて表示する
    def get_department(self, obj):
        return obj.institution.department
    get_department.short_description = '診療科目'

    def get_institution_phone(self, obj):
        return obj.institution.phone
    get_institution_phone.short_description = '電話番号'
