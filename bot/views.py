from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, FollowEvent
from django.utils import timezone
from datetime import timedelta
from openai import OpenAI
import time
import re
import traceback

from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, GarbageCalendar
from members.models import AiMember

# ★Excelに入力した「市町村」と「地区」の文字と完全に一致させる必要があります
REGION_MAP = {
    'miyazaki_kita_a': ('宮崎市', '北A地区'),
    'miyazaki_kita_b': ('宮崎市', '北B地区'),
    'miyazaki_minami_a': ('宮崎市', '南A地区'),
    'miyazaki_minami_b': ('宮崎市', '南B地区'),
}

@csrf_exempt
def callback(request, politician_slug):
    politician = get_object_or_404(Politician, slug=politician_slug)
    line_bot_api = LineBotApi(politician.line_access_token)
    handler = WebhookHandler(politician.line_channel_secret)

    signature = request.META.get('HTTP_X_LINE_SIGNATURE', '')
    body = request.body.decode('utf-8')


    # ゴミの種類に応じて色を自動判定する関数
    def get_garbage_color(garbage_type):
        if "可燃" in garbage_type or "燃える" in garbage_type: return "#FF3B30" # 赤
        if "プラ" in garbage_type: return "#007AFF" # 青
        if "資源" in garbage_type or "ペット" in garbage_type or "ダンボール" in garbage_type: return "#34C759" # 緑
        if "不燃" in garbage_type or "燃えない" in garbage_type or "金属" in garbage_type: return "#FF9500" # オレンジ
        return "#8E8E93" # グレー（その他）

    # 💡【AI用】裏でAIに渡すためのテキストカレンダー
    def get_db_schedule_text():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        muni_dist = REGION_MAP.get(politician.gomi_region)
        
        if not muni_dist:
            return "未設定", "未設定", "※地区情報が設定されていません。"
        
        muni_name, dist_name = muni_dist
        schedules = GarbageCalendar.objects.filter(
            municipality=muni_name, district=dist_name,
            collection_date__gte=today, collection_date__lte=today + timedelta(days=30)
        ).order_by('collection_date')
        
        if schedules.exists():
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            lines = []
            for s in schedules:
                w = weekdays[s.collection_date.weekday()]
                line = f"・{s.collection_date.strftime('%m/%d')}({w}): {s.garbage_type}"
                if s.notes: line += f" ※{s.notes}"
                lines.append(line)
            return muni_name, dist_name, "\n".join(lines)
        return muni_name, dist_name, "※直近30日の収集予定は登録されていません。"

    # 💡【人間用】LINE画面に表示する美しいビジュアルカレンダー
    def get_flex_schedule():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        muni_dist = REGION_MAP.get(politician.gomi_region)
        
        if not muni_dist:
            return TextSendMessage(text="※地区情報が設定されていません。")
        
        muni_name, dist_name = muni_dist
        schedules = GarbageCalendar.objects.filter(
            municipality=muni_name, district=dist_name,
            collection_date__gte=today, collection_date__lte=today + timedelta(days=30)
        ).order_by('collection_date')

        if not schedules.exists():
            return TextSendMessage(text=f"【{muni_name} {dist_name}】\n直近30日の収集予定は登録されていません。")

        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        contents = []
        
        for s in schedules:
            w = weekdays[s.collection_date.weekday()]
            # 日付（例：2/25(水)）
            date_str = f"{s.collection_date.month}/{s.collection_date.day}({w})"
            color = get_garbage_color(s.garbage_type)
            
            # 1日分の行を作成
            row = {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": date_str, "size": "sm", "weight": "bold", "color": "#555555", "flex": 3},
                    {"type": "text", "text": s.garbage_type, "size": "sm", "weight": "bold", "color": color, "flex": 5}
                ]
            }
            # 注意書きがあれば追加
            if s.notes:
                row["contents"].append({"type": "text", "text": s.notes, "size": "xs", "color": "#888888", "flex": 4, "wrap": True})
            contents.append(row)

            # 行の間に薄い線を引く
            contents.append({"type": "separator", "margin": "md"})

        # ビジュアルパネルの大枠を組み立てる
        bubble = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box", "layout": "vertical", "backgroundColor": "#1DB446",
                "contents": [
                    {"type": "text", "text": "📅 ゴミ収集カレンダー", "weight": "bold", "size": "lg", "color": "#FFFFFF"},
                    {"type": "text", "text": f"{muni_name} {dist_name}（直近30日）", "size": "xs", "color": "#E5F7ED", "margin": "sm"}
                ]
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": contents
            }
        }
        return FlexSendMessage(alt_text="ゴミ出しカレンダー", contents=bubble)   


    def get_ai_response(user_text):
        if not politician.openai_api_key: return "AI設定未完了"
        client = OpenAI(api_key=politician.openai_api_key.strip())
        
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        weekday_str = ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()]
        
        muni_name, dist_name, schedule_text = get_db_schedule_text()
        
        # 💡【修正】Windows特有の文字化けエラーを防ぐため、年月日の作り方を安全な形式に変更しました
        today_str = f"{today.year}年{today.month:02d}月{today.day:02d}日"
        
        system_prompt = (
            f"{politician.system_prompt}\n\n"
            f"あなたは自治体の優秀な案内アシスタントです。以下の【直近の収集カレンダー】の事実のみに基づいて回答してください。\n"
            f"絶対に自分で計算や推測をせず、カレンダーに記載されている日付とゴミの種類だけを答えてください。\n"
            f"カレンダーにない日付を聞かれた場合は「データがありません」と答えてください。\n\n"
            f"【現在の日時】\n"
            f"今日: {today_str} ({weekday_str}曜日)\n\n"
            f"【地区情報】{muni_name} {dist_name}\n"
            f"【直近の収集カレンダー（今日から30日間）】\n"
            f"{schedule_text}"
        )
        
        try:
            response = client.chat.completions.create(
                model=politician.ai_model_name,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
            )
            return response.choices[0].message.content
        except Exception as e: return f"AIエラー: {str(e)}"

    @handler.add(FollowEvent)
    def handle_follow(event):
        member, _ = AiMember.objects.get_or_create(line_user_id=event.source.user_id)
        member.registration_step = 0
        member.save()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"【{politician.name}】へようこそ！お名前を教えてください。"))

    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event):
        try:
            user_text = event.message.text.strip()
            line_user_id = event.source.user_id
            member, _ = AiMember.objects.get_or_create(line_user_id=line_user_id)

            if member.registration_step < 3:
                if member.registration_step == 0:
                    member.registration_step = 1
                    member.save()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="お名前をフルネームでお願いします。"))
                elif member.registration_step == 1:
                    member.real_name = user_text
                    member.registration_step = 2
                    member.save()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="班名またはご住所をお願いします。"))
                elif member.registration_step == 2:
                    member.address = user_text
                    member.registration_step = 3
                    member.save()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="登録完了！メニューから情報を選んでください。"))
                return
            
            # ▼ ゴミ出しカレンダーが押された時、ビジュアルパネル（Flex Message）をそのまま返す
            if user_text == "ゴミ出しカレンダー":
                flex_msg = get_flex_schedule()
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return

            # 💡【今回ここを新規追加します】
            if user_text == "お問い合わせ":
                # ↓ご自身のメールアドレスに書き換えてください
                contact_email = "winwinmiyazaki@miyazaki-catv.ne.jp" 
                msg = f"ご不明な点やご相談は、以下のメールアドレスまでお気軽にお問い合わせください。\n\n✉️ {contact_email}\n\n※送信の際は、お名前と地区名を添えていただけますとスムーズです。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                return

            # (前略) お問い合わせやゴミ出しカレンダーの処理...

            # ▼ 💡【変更】教材一覧の表示（カルーセル）
            if user_text in ["案内一覧", "教材一覧", "ルール確認"]:
                # CourseAssignment（自治会に紐づいた案内）を取得
                assignments = CourseAssignment.objects.filter(politician=politician).order_by('id')
                if not assignments.exists():
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="現在、案内（教材）は準備中です。"))
                    return
                
                contents = []
                for a in assignments:
                    course = a.course
                    bubble = {
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": "自治会のご案内", "color": "#1DB446", "size": "sm", "weight": "bold"},
                                {"type": "text", "text": course.title, "weight": "bold", "size": "xl", "margin": "md", "wrap": True},
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {
                                    "type": "button", "style": "primary", "color": "#1DB446",
                                    "action": {"type": "message", "label": "確認を始める", "text": f"教材開始:{course.title}"}
                                }
                            ]
                        }
                    }
                    contents.append(bubble)
                flex_message = FlexSendMessage(alt_text="案内一覧", contents={"type": "carousel", "contents": contents})
                line_bot_api.reply_message(event.reply_token, flex_message)
                return

            # ▼ 💡【変更】学習（案内）のサイクル処理
            if user_text.startswith("教材開始:") or user_text.startswith("教材進捗:") or user_text.startswith("教材次へ:") or user_text.startswith("教材終了:") or user_text.startswith("教材復習:"):
                parts = user_text.split(":")
                action = parts[0]
                title = parts[1]
                
                course = Course.objects.filter(title=title).first()
                if not course:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="情報が見つかりませんでした。"))
                    return

                # 進捗の取得・作成（マルチテナント対応済）
                progress, _ = UserProgress.objects.get_or_create(
                    line_user_id=line_user_id,
                    current_course=course,
                    defaults={'politician': politician, 'last_completed_order': 0}
                )

                # --- 終了処理 ---
                if action == "教材終了":
                    reply_text = f"☕ ご確認お疲れ様でした！\n『{course.title}』の続きは、メニューからいつでも再開できます。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # --- 復習（見返し）処理 ---
                if action == "教材復習":
                    completed_contents = CourseContent.objects.filter(
                        course=course,
                        order__lte=progress.last_completed_order
                    ).order_by('order')

                    if not completed_contents.exists():
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="まだ見返せる案内がありません。まずは確認を進めましょう！"))
                        return
                    
                    reply_text = f"📚 『{course.title}』の確認リストです\n\n"
                    for content in completed_contents:
                        reply_text += f"■ {content.title}\n"
                        if content.video_url:
                            reply_text += f"🎬 {content.video_url}\n"
                        reply_text += "\n"
                    
                    reply_text += "何度でも見返して確認できます✨"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # --- 進捗の保存処理 ---
                if action == "教材進捗":
                    completed_order = int(parts[2])
                    if progress.last_completed_order < completed_order:
                        progress.last_completed_order = completed_order
                        progress.save()
                    
                    next_content = CourseContent.objects.filter(
                        course=course,
                        order__gt=progress.last_completed_order
                    ).order_by('order').first()

                    if next_content:
                        bubble = {
                            "type": "bubble",
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "✅ 記録を保存しました", "weight": "bold", "color": "#1DB446", "size": "md"},
                                    {"type": "text", "text": "続けて次の案内に進みますか？", "wrap": True, "size": "sm", "margin": "md"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "vertical", "spacing": "sm",
                                "contents": [
                                    {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "次に進む", "text": f"教材次へ:{course.title}"}},
                                    {"type": "button", "style": "secondary", "action": {"type": "message", "label": "一旦終了する", "text": f"教材終了:{course.title}"}}
                                ]
                            }
                        }
                        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="次に進みますか？", contents=bubble))
                    else:
                        reply_text = f"🎉 おめでとうございます！\n『{course.title}』の全ご案内が完了しました！"
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # --- 開始・次へ の処理 ---
                if action == "教材開始" or action == "教材次へ":
                    next_content = CourseContent.objects.filter(
                        course=course,
                        order__gt=progress.last_completed_order
                    ).order_by('order').first()

                    if next_content:
                        # テキストメッセージの作成
                        msg_text = f"📖 【{next_content.title}】\n\n{next_content.message_text}"
                        if next_content.video_url:
                            msg_text += f"\n\n🎬 参考動画はこちら:\n{next_content.video_url}"
                        
                        text_msg = TextSendMessage(text=msg_text)
                        
                        # ボタン（FlexMessage）の作成
                        bubble = {
                            "type": "bubble",
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [{"type": "text", "text": "確認が終わったらボタンを押して記録しましょう👇", "wrap": True, "size": "sm", "color": "#666666"}]
                            },
                            "footer": {
                                "type": "box", "layout": "horizontal", "spacing": "sm",
                                "contents": [
                                    {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "確認完了", "text": f"教材進捗:{course.title}:{next_content.order}"}},
                                    {"type": "button", "style": "secondary", "action": {"type": "message", "label": "スキップ", "text": f"教材進捗:{course.title}:{next_content.order}"}}
                                ]
                            }
                        }
                        flex_msg = FlexSendMessage(alt_text="確認完了ボタン", contents=bubble)
                        line_bot_api.reply_message(event.reply_token, [text_msg, flex_msg])
                    else:
                        bubble = {
                            "type": "bubble",
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "🎉 すべて確認済みです", "weight": "bold", "color": "#1DB446", "size": "md"},
                                    {"type": "text", "text": f"すでに『{course.title}』を最後まで確認済みです！\n\n復習リストから過去の案内を再確認できます。", "wrap": True, "size": "sm", "margin": "md"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "vertical", "spacing": "sm",
                                "contents": [
                                    {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "復習リストを見る", "text": f"教材復習:{course.title}"}}
                                ]
                            }
                        }
                        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="全確認完了", contents=bubble))
                    return

            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_ai_response(user_text)))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"エラー: {str(e)}"))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")
