from django.contrib import admin
import requests
from .models import Facility, Reservation

@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'politician', 'is_active')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('facility', 'user_name', 'date', 'start_time', 'end_time', 'status')
    list_filter = ('status', 'facility')
    search_fields = ('user_name', 'user_phone')
    
    # 🛡️ 防衛的視点：LINE IDはシステムが自動取得するため、手動編集を禁止して保護する
    readonly_fields = ('applicant_line_id',)

    # ▼ 一括操作アクションの登録 ▼
    actions = ['make_approved']

    @admin.action(description='選択した予約を「承認済」にする')
    def make_approved(self, request, queryset):
        # ⚠️ 注意: 一括操作（update）では save_model を経由しないため、LINE通知は飛びません。
        # LINE通知を出したい場合は、一覧画面からではなく、個別の編集画面から「承認」に変更して保存してください。
        queryset.update(status='APPROVED')

    # ▼ 個別編集での保存時にLINE通知を発火させる処理 ▼
    def save_model(self, request, obj, form, change):
        if change:
            old_obj = Reservation.objects.get(pk=obj.pk)
            
            # ステータスが「申請中」から「承認」に変わった瞬間だけ発火
            if old_obj.status == 'PENDING' and obj.status == 'APPROVED':
                self.send_line_reply(obj, "✅ ご予約が承認されました！")
                
            # ステータスが「申請中」から「却下」に変わった瞬間だけ発火
            elif old_obj.status == 'PENDING' and obj.status == 'REJECTED':
                self.send_line_reply(obj, "❌ 誠に申し訳ありませんが、ご予約が却下されました。")
                
        super().save_model(request, obj, form, change)

    def send_line_reply(self, reservation, result_text):
        """申請者のLINEへ審査結果を自動通知する処理"""
        # 宛先ID(applicant_line_id)がない、または自治会のLINE設定がない場合はエラーを防ぐため何もしない
        if not reservation.applicant_line_id or not reservation.facility.politician.line_access_token:
            return

        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {reservation.facility.politician.line_access_token}"
        }
        
        msg = (
            f"{result_text}\n\n"
            f"施設: {reservation.facility.name}\n"
            f"日時: {reservation.date.strftime('%Y/%m/%d')} {reservation.start_time.strftime('%H:%M')}〜{reservation.end_time.strftime('%H:%M')}\n"
            f"申請者: {reservation.user_name} 様\n\n"
            f"※当日はお気をつけてお越しください。"
        )
        
        data = {
            "to": reservation.applicant_line_id,
            "messages": [{"type": "text", "text": msg}]
        }
        
        try:
            requests.post(url, headers=headers, json=data, timeout=5)
        except Exception as e:
            print(f"住民へのLINE返信エラー: {e}")
            