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

    # 💡【新規追加】DBから直近30日のカレンダーを検索してテキストにする関数
    def get_db_schedule():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        muni_dist = REGION_MAP.get(politician.gomi_region)
        
        if not muni_dist:
            return "未設定", "未設定", "※地区情報が設定されていません。"
        
        muni_name, dist_name = muni_dist
        schedules = GarbageCalendar.objects.filter(
            municipality=muni_name,
            district=dist_name,
            collection_date__gte=today,
            collection_date__lte=today + timedelta(days=30)
        ).order_by('collection_date')
        
        if schedules.exists():
            weekdays = ["月", "火", "水", "木", "金", "土", "日"]
            lines = []
            for s in schedules:
                w = weekdays[s.collection_date.weekday()]
                line = f"・{s.collection_date.strftime('%m/%d')}({w}): {s.garbage_type}"
                if s.notes:
                    line += f" ※{s.notes}"
                lines.append(line)
            return muni_name, dist_name, "\n".join(lines)
        return muni_name, dist_name, "※直近30日の収集予定は登録されていません。"

    def get_ai_response(user_text):
        if not politician.openai_api_key: return "AI設定未完了"
        client = OpenAI(api_key=politician.openai_api_key.strip())
        
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        weekday_str = ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()]
        
        muni_name, dist_name, schedule_text = get_db_schedule()
        
        system_prompt = (
            f"{politician.system_prompt}\n\n"
            f"あなたは自治体の優秀な案内アシスタントです。以下の【直近の収集カレンダー】の事実のみに基づいて回答してください。\n"
            f"絶対に自分で計算や推測をせず、カレンダーに記載されている日付とゴミの種類だけを答えてください。\n"
            f"カレンダーにない日付を聞かれた場合は「データがありません」と答えてください。\n\n"
            f"【現在の日時】\n"
            f"今日: {today.strftime('%Y年%m月%d日')} ({weekday_str}曜日)\n\n"
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

            # 💡【新規追加】リッチメニュー「ゴミ出しカレンダー」の処理
            if user_text == "ゴミ出しカレンダー":
                muni_name, dist_name, schedule_text = get_db_schedule()
                msg = f"📅 【{muni_name} {dist_name}】のゴミ出しカレンダー（直近30日）\n\n{schedule_text}\n\n※「明日のゴミは？」など、分からないことはそのまま私（AI）に聞いてくださいね！"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                return

            # 2. 教材・案内アクション
            if ":" in user_text:
                prefix, title = user_text.split(":", 1)
                if prefix in ["教材開始", "教材進捗", "教材次へ", "教材終了"]:
                    course = Course.objects.filter(title=title).first()
                    if not course:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="情報が見つかりません。"))
                        return
                    
                    if prefix == "教材開始":
                        progress, _ = UserProgress.objects.update_or_create(
                            line_user_id=line_user_id,
                            current_course=course,
                            defaults={'politician': politician, 'last_completed_order': 0}
                        )
                    else:
                        progress, _ = UserProgress.objects.get_or_create(
                            line_user_id=line_user_id,
                            current_course=course,
                            defaults={'politician': politician, 'last_completed_order': 0}
                        )
                    
                    if prefix == "教材終了":
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ご確認ありがとうございました。"))
                        return

                    content = CourseContent.objects.filter(course=course, order__gt=progress.last_completed_order).first()
                    if content:
                        progress.last_completed_order = content.order
                        progress.save()
                        
                        msg = f"【{content.title}】\n\n{content.message_text}"
                        buttons = []
                        
                        if content.video_url:
                            buttons.append({
                                "type": "button", "style": "primary", "color": "#E52020",
                                "action": {"type": "uri", "label": "🎥 動画を見る", "uri": content.video_url}
                            })

                        if not CourseContent.objects.filter(course=course, order__gt=content.order).exists():
                            buttons.append({"type": "button", "style": "secondary", "action": {"type": "message", "label": "完了", "text": f"教材終了:{course.title}"}})
                        else:
                            buttons.append({"type": "button", "style": "primary", "action": {"type": "message", "label": "次へ", "text": f"教材次へ:{course.title}"}})
                        
                        flex = FlexSendMessage(alt_text=content.title, contents={
                            "type": "bubble", 
                            "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": msg, "wrap": True}]},
                            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": buttons}
                        })
                        line_bot_api.reply_message(event.reply_token, flex)
                    else:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="すべての内容が完了しています。"))
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
                        "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": a.course.title, "weight": "bold", "size": "xl", "wrap": True}]},
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