from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, FollowEvent
from django.utils import timezone
from openai import OpenAI
import time
import re
import traceback

from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment
from members.models import AiMember

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
        if not politician.openai_api_key: return "AI設定未完了"
        client = OpenAI(api_key=politician.openai_api_key.strip())
        
        region_name = politician.get_gomi_region_display()
        schedule = GOMI_SCHEDULE_DATA.get(politician.gomi_region, "市役所確認")
        
        system_prompt = f"{politician.system_prompt}\n\n【地区情報】{region_name}\n【スケジュール】{schedule}\n今日の日付:{timezone.now().strftime('%Y-%m-%d')}"
        
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

            # 1. 登録フロー
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

            # 2. 教材・案内アクション (「:」を含むものを最優先で判定)
            if ":" in user_text:
                prefix, title = user_text.split(":", 1)
                if prefix in ["教材開始", "教材進捗", "教材次へ", "教材終了"]:
                    course = Course.objects.filter(title=title).first()
                    if not course:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="情報が見つかりません。"))
                        return
                    
                    progress, _ = UserProgress.objects.get_or_create(politician=politician, line_user_id=line_user_id, current_course=course)
                    
                    if prefix == "教材終了":
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ご確認ありがとうございました。"))
                        return

                    # 次のコンテンツを取得
                    content = CourseContent.objects.filter(course=course, order__gt=progress.last_completed_order).first()
                    if content:
                        progress.last_completed_order = content.order
                        progress.save()
                        
                        msg = f"【{content.title}】\n\n{content.message_text}"
                        buttons = [{"type": "button", "style": "primary", "action": {"type": "message", "label": "次へ", "text": f"教材次へ:{course.title}"}}]
                        
                        # 最後なら「終了」ボタン
                        if not CourseContent.objects.filter(course=course, order__gt=content.order).exists():
                            buttons = [{"type": "button", "style": "secondary", "action": {"type": "message", "label": "完了", "text": f"教材終了:{course.title}"}}]
                        
                        flex = FlexSendMessage(alt_text=content.title, contents={
                            "type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": msg, "wrap": True}]},
                            "footer": {"type": "box", "layout": "vertical", "contents": buttons}
                        })
                        line_bot_api.reply_message(event.reply_token, flex)
                    return

            # 3. 案内一覧
            if user_text in ["案内一覧", "教材一覧", "ルール確認"]:
                assignments = CourseAssignment.objects.filter(politician=politician)
                if not assignments:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="準備中"))
                    return
                
                bubbles = []
                for a in assignments:
                    bubbles.append({
                        "type": "bubble",
                        "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": a.course.title, "weight": "bold", "size": "xl"}]},
                        "footer": {"type": "box", "layout": "vertical", "contents": [{"type": "button", "style": "primary", "action": {"type": "message", "label": "開く", "text": f"教材開始:{a.course.title}"}}]}
                    })
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="一覧", contents={"type": "carousel", "contents": bubbles}))
                return

            # 4. AI応答
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_ai_response(user_text)))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"エラー: {str(e)}"))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")
