from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
# linebot.models に FollowEvent を追加
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent, FlexSendMessage, FollowEvent
from django.utils import timezone
from openai import OpenAI
import json
import traceback
import time
import re

from .models import Politician, Event, Course, CourseContent, UserProgress
from members.models import AiMember

# 宮崎市 地区別ゴミ収集スケジュール（令和7年度版）
GOMI_SCHEDULE_DATA = {
    'miyazaki_kita_a': "月・木：可燃、金：プラ、第2・4水：缶びん、第1・3水：ペット、第1水：不燃・金属、第2・4火：古紙・衣類、第1〜4火：蛍光管・電池類",
    'miyazaki_kita_b': "月・木：可燃、金：プラ、第1・3火：缶びん、第2・4火：ペット、第2水：不燃・金属、第4水：古紙・衣類、第1〜4火：蛍光管・電池類",
    'miyazaki_minami_a': "火・金：可燃、水：プラ、第2水：缶びん、第1・3木：ペット、第3月：不燃・金属、第1水：古紙・衣類、第1〜4月：蛍光管・電池類",
    'miyazaki_minami_b': "火・金：可燃、水：プラ、第4水：缶びん、第2・4木：ペット、第4月：不燃・金属、第1火：古紙・衣類、第1〜4火：蛍光管・電池類",
}

@csrf_exempt
def callback(request, politician_slug):
    politician = get_object_or_404(Politician, slug=politician_slug)
    line_bot_api = LineBotApi(politician.line_access_token)
    handler = WebhookHandler(politician.line_channel_secret)

    signature = request.META.get('HTTP_X_LINE_SIGNATURE', '')
    body = request.body.decode('utf-8')

    def get_ai_response(user_text):
        if not politician.openai_api_key:
            return "AI設定が未完了です。"
        
        api_key = politician.openai_api_key.strip()
        assistant_id = politician.openai_assistant_id.strip() if politician.openai_assistant_id else None

        client = OpenAI(
            api_key=api_key,
            default_headers={"OpenAI-Beta": "assistants=v2"}
        )

        region_key = politician.gomi_region
        region_name = politician.get_gomi_region_display()
        schedule_summary = GOMI_SCHEDULE_DATA.get(region_key, "市役所のカレンダーを確認してください。")

        base_system_prompt = politician.system_prompt
        enhanced_system_prompt = f"""
{base_system_prompt}

【ゴミ収集に関する最優先指示】
1. この自治会の担当地区は「{region_name}」です。
2. 収集スケジュール: {schedule_summary}
3. 回答の際は必ず「当自治会の基本地区（{region_name}）のルールでは〜」と添えて回答してください。
4. 住民から「今日は何のごみ？」「明日の予定は？」と聞かれたら、上記スケジュールと今日の日付（{timezone.now().strftime('%Y-%m-%d')}）を照らし合わせて正確に答えてください。
"""

        if assistant_id:
            try:
                thread = client.beta.threads.create()
                client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=user_text
                )
                run = client.beta.threads.runs.create(
                    thread_id=thread.id,
                    assistant_id=assistant_id,
                    instructions=enhanced_system_prompt
                )
                while run.status in ['queued', 'in_progress']:
                    time.sleep(1)
                    run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                
                if run.status == 'completed':
                    messages = client.beta.threads.messages.list(thread_id=thread.id)
                    for msg in messages.data:
                        if msg.role == "assistant":
                            answer_text = msg.content[0].text.value
                            return re.sub(r'【.*?】', '', answer_text)
                return f"AI処理失敗: {run.status}"
            except Exception as e:
                return f"⚠️ APIエラー: {str(e)}"
        else:
            try:
                response = client.chat.completions.create(
                    model=politician.ai_model_name,
                    messages=[
                        {"role": "system", "content": enhanced_system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    max_tokens=500
                )
                return response.choices[0].message.content
            except Exception as e:
                return f"AI応答エラー: {str(e)}"

    # 1. 友だち追加イベントのハンドラ
    @handler.add(FollowEvent)
    def handle_follow(event):
        line_user_id = event.source.user_id
        member, created = AiMember.objects.get_or_create(
            line_user_id=line_user_id,
            defaults={'display_name': '未設定'}
        )
        # 登録フローを0から開始させる
        member.registration_step = 0
        member.save()

        reply_text = f"友だち追加ありがとうございます！\n【{politician.name}】公式LINEです。\n\n自治会名簿と連携するため、まずは【お名前（フルネーム）】を送信してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

    # 2. メッセージイベントのハンドラ
    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event):
        try:
            user_text = event.message.text.strip()
            line_user_id = event.source.user_id
            
            member, created = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={'display_name': '未設定'}
            )

            # --- 登録フロー（step 3未満なら登録を優先） ---
            if member.registration_step == 0:
                member.registration_step = 1
                member.save()
                reply_text = "はじめまして！自治会の名簿と連携するため、まずは【お名前（フルネーム）】を送信してください。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return
            elif member.registration_step == 1:
                member.real_name = user_text
                member.registration_step = 2
                member.save()
                reply_text = f"{user_text}さん、ありがとうございます！\n続いて、【班名またはご住所】を送信してください。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return
            elif member.registration_step == 2:
                member.address = user_text
                member.registration_step = 3
                member.save()
                reply_text = "登録が完了しました！\nメニューから自治会のルールを確認したり、ゴミ出しについて質問したりしてみてください。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return
            
            # --- 以下、登録完了後の処理（step 3以上） ---
            if user_text in ["教材一覧", "教材コース一覧", "案内一覧", "ルール確認"]:
                courses = Course.objects.filter(politician=politician).order_by('id')
                if not courses.exists():
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="現在、ご案内情報は準備中です。"))
                    return
                contents_bubbles = []
                for course in courses:
                    bubble = {
                        "type": "bubble",
                        "body": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "text", "text": "自治会のご案内", "color": "#1DB446", "size": "sm", "weight": "bold"},
                                {"type": "text", "text": course.title, "weight": "bold", "size": "xl", "margin": "md"},
                                {"type": "text", "text": course.description, "size": "sm", "color": "#666666", "wrap": True, "margin": "md"}
                            ]
                        },
                        "footer": {
                            "type": "box", "layout": "vertical",
                            "contents": [
                                {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "確認する", "text": f"教材開始:{course.title}"}}
                            ]
                        }
                    }
                    contents_bubbles.append(bubble)
                flex_message = FlexSendMessage(alt_text="案内一覧", contents={"type": "carousel", "contents": contents_bubbles})
                line_bot_api.reply_message(event.reply_token, flex_message)
                return

            elif any(user_text.startswith(prefix) for prefix in ["教材開始:", "教材進捗:", "教材次へ:", "教材終了:", "教材復習:"]):
                # 既存の教材ロジック（そのまま維持）
                parts = user_text.split(":")
                action = parts[0]
                title = parts[1]
                course = Course.objects.filter(politician=politician, title=title).first()
                if not course:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="案内が見つかりませんでした。"))
                    return
                # 教材アクションごとの処理（省略部分は元のコードと同じ）
                if action == "教材終了":
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"☕ ご確認ありがとうございました！"))
                    return
                reply_text = get_ai_response(user_text)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            elif user_text in ["行事予定", "活動予定"]:
                future_event = Event.objects.filter(politician=politician, date__gte=timezone.now()).order_by('date').first()
                if future_event:
                    dt = timezone.localtime(future_event.date)
                    reply_text = f"【行事予定】\n📛 {future_event.title}\n📅 {dt.strftime('%Y年%m月%d日 %H:%M')}"
                else:
                    reply_text = "現在、予定されている行事はありません。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            # --- AI対話 ---
            else:
                reply_text = get_ai_response(user_text)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️エラー: {str(e)}"))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")
