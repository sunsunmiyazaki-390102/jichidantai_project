import requests
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from .forms import ReservationForm
from .models import Facility, Reservation
from bot.models import Politician

# ==========================================
# 🛡️ 外部API通信モジュール（防衛的設計）
# ==========================================
def send_line_notification(access_token, to_id, message_text):
    """LINEのPush APIを使って通知を送信する"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    data = {
        "to": to_id,
        "messages": [{"type": "text", "text": message_text}]
    }
    try:
        # timeout=5 を設定し、LINE側のサーバー障害時にこちらのシステムがフリーズするのを防ぐ
        response = requests.post(url, headers=headers, json=data, timeout=5)
        response.raise_for_status()
    except Exception as e:
        # ⚠️ 通信に失敗しても、住民にはエラーを見せずシステムを止めない
        print(f"LINE通知エラー: {e}")

# ==========================================
# 1. 申請受付ビュー（LIFF ID取得・LINE通知機能付き）
# ==========================================
def calendar_view(request, slug):
    """住民向けカレンダー表示と申請受付"""
    politician = get_object_or_404(Politician, slug=slug)
    facilities = Facility.objects.filter(politician=politician, is_active=True)
    
    if request.method == 'POST':
        form = ReservationForm(request.POST, politician=politician)
        if form.is_valid():
            # 🛡️ commit=False で一旦保存を止め、フォーム外のデータをセットする
            reservation = form.save(commit=False)
            
            # 🔴 重要：HTMLのLIFF SDKが取得したLINE IDを保存する
            line_id = request.POST.get('applicant_line_id')
            if line_id:
                reservation.applicant_line_id = line_id
            
            reservation.status = 'PENDING'
            reservation.save()
            
            # 🎯 役員へのLINE通知処理
            if politician.line_access_token and getattr(politician, 'notification_line_id', None):
                msg = (
                    f"🔔 【新規の施設予約申請】\n\n"
                    f"施設: {reservation.facility.name}\n"
                    f"日時: {reservation.date.strftime('%Y/%m/%d')} {reservation.start_time.strftime('%H:%M')}〜{reservation.end_time.strftime('%H:%M')}\n"
                    f"目的: {reservation.purpose}\n"
                    f"申請者: {reservation.user_name}\n"
                    f"連絡先: {reservation.user_phone}\n\n"
                    f"▼以下の管理画面から「承認」または「却下」を行ってください。\n"
                    f"https://jichidantai.jp/admin/reservations/reservation/"
                )
                send_line_notification(politician.line_access_token, politician.notification_line_id, msg)

            messages.success(request, '予約申請を送信しました。役員による承認をお待ちください。')
            return redirect('reservations:calendar', slug=slug)
        else:
            messages.error(request, '入力内容に誤りがあるか、時間が重複しています。')
    else:
        form = ReservationForm(politician=politician)

    context = {
        'politician': politician,
        'facilities': facilities,
        'form': form,
    }
    return render(request, 'reservations/calendar.html', context)


# ==========================================
# 2. カレンダーデータ送信用API
# ==========================================
def events_api(request, slug):
    """カレンダーライブラリ（FullCalendar）に予約データを渡すためのJSON API"""
    politician = get_object_or_404(Politician, slug=slug)
    
    # 該当自治会の施設で、承認済または承認待ちの予約を取得
    reservations = Reservation.objects.filter(
        facility__politician=politician,
        status__in=['PENDING', 'APPROVED']
    )
        
    events = []
    for res in reservations:
        # 🛡️ 運営側の防衛的視点: 個人情報はJSONに含めず、タイトルに最小限の情報のみ表示
        color = '#28a745' if res.status == 'APPROVED' else '#ffc107'
        title = f"[{res.facility.name}] {res.user_name}"
        if res.status == 'PENDING':
            title += " (申請中)"
            
        events.append({
            'title': title,
            'start': f"{res.date.isoformat()}T{res.start_time.strftime('%H:%M:%S')}",
            'end': f"{res.date.isoformat()}T{res.end_time.strftime('%H:%M:%S')}",
            'color': color,
        })
        
    return JsonResponse(events, safe=False)
