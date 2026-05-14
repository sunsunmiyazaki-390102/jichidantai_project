# ==========================================
# 1. Python標準ライブラリ
# ==========================================
import calendar
import re
import time
import traceback
from datetime import timedelta
from urllib.parse import parse_qsl

# ==========================================
# 2. サードパーティ・ライブラリ (LINE, OpenAI)
# ==========================================
import openai  # 🔴 追加：RateLimitErrorをキャッチするために全体をインポート
from openai import OpenAI
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, 
    FollowEvent, PostbackEvent, TemplateSendMessage, CarouselTemplate, 
    CarouselColumn, PostbackAction
)

# ==========================================
# 3. Django コア機能
# ==========================================
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, Http404
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

# ==========================================
# 4. 自作アプリのモデル群
# ==========================================
from members.models import AiMember
from library.models import LibraryDocument

from events.models import Announcement, Survey, HolidayDutySchedule 

from bot.models import (
    Politician, Event, Course, CourseContent, UserProgress, 
    CourseAssignment, GarbageCalendar, EmergencyEvent, EmergencyResponse, 
    CityEmergencyEvent, CityEmergencyResponse, PublicPageConfig, Condolence,
    TenantLLMQuota  # 🔴 追加：AI利用枠モデル
)

@login_required
def library_list(request):
    """
    住民が所属する自治会の資料のみを表示するセキュアなビュー
    """
    user_member = request.user.member 
    
    documents = LibraryDocument.active_objects.filter(
        politician=user_member.politician,
        access_level='PUBLIC'
    ).order_by('-fiscal_year', '-created_at')

    paginator = Paginator(documents, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'library/document_list.html', {
        'page_obj': page_obj,
    })

@csrf_exempt
def callback(request, politician_slug):
    politician = get_object_or_404(Politician, slug=politician_slug)
    line_bot_api = LineBotApi(politician.line_access_token)
    handler = WebhookHandler(politician.line_channel_secret)

    signature = request.META.get('HTTP_X_LINE_SIGNATURE', '')
    body = request.body.decode('utf-8')

    def get_garbage_color(garbage_type):
        if "可燃" in garbage_type or "燃える" in garbage_type: return "#FF3B30"
        if "プラ" in garbage_type: return "#007AFF"
        if "資源" in garbage_type or "ペット" in garbage_type or "ダンボール" in garbage_type: return "#34C759"
        if "不燃" in garbage_type or "燃えない" in garbage_type or "金属" in garbage_type: return "#FF9500"
        return "#8E8E93"

    def get_db_schedule_text():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        
        muni_name = politician.gomi_municipality
        dist_name = politician.gomi_district
        
        if not muni_name or not dist_name:
            return "未設定", "未設定", "※地区情報が設定されていません。"
        
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

    def get_flex_schedule():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        
        muni_name = politician.gomi_municipality
        dist_name = politician.gomi_district
        
        if not muni_name or not dist_name:
            return TextSendMessage(text="※地区情報が設定されていません。\n管理者に「市町村」と「地区」の設定をご依頼ください。")
        
        schedules = GarbageCalendar.objects.filter(
            municipality=muni_name, district=dist_name,
            collection_date__gte=today, collection_date__lte=today + timedelta(days=30)
        ).order_by('collection_date')

        if not schedules.exists():
            return TextSendMessage(text=f"【{muni_name} {dist_name}】\n直近30日の収集予定は登録されていません。")

        grouped_schedules = {}
        for s in schedules:
            date_key = s.collection_date.strftime('%Y-%m-%d')
            if date_key not in grouped_schedules:
                grouped_schedules[date_key] = []
            grouped_schedules[date_key].append(s)

        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        contents = []
        
        for date_key, items in grouped_schedules.items():
            date_obj = items[0].collection_date
            w = weekdays[date_obj.weekday()]
            date_str = f"{date_obj.month}/{date_obj.day}({w})"
            
            spans = []
            for i, item in enumerate(items):
                color = get_garbage_color(item.garbage_type)
                spans.append({"type": "span", "text": item.garbage_type, "color": color, "weight": "bold"})
                
                if item.notes:
                    spans.append({"type": "span", "text": f"({item.notes})", "color": "#888888", "size": "xs"})
                
                if i < len(items) - 1:
                    spans.append({"type": "span", "text": " / ", "color": "#CCCCCC"})
            
            row = {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "margin": "md",
                "contents": [
                    {"type": "text", "text": date_str, "size": "sm", "weight": "bold", "color": "#555555", "flex": 3},
                    {"type": "text", "contents": spans, "size": "sm", "flex": 5, "wrap": True}
                ]
            }
            contents.append(row)
            contents.append({"type": "separator", "margin": "md"})

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

    # ==========================================
    # ▼▼▼ 修正：防衛的ロジックを追加したAI応答 ▼▼▼
    # ==========================================
    def get_ai_response(user_text):
        if not politician.openai_api_key: return "AI設定未完了"

        # 🛡️ 運営側の防衛的視点: システム（DB）で設定した月間利用枠を超過していないかチェック
        if hasattr(politician, 'llm_quota'):
            if not politician.llm_quota.can_use_ai():
                return "【システム通知】当月のAI自動応答システムのご利用上限に達しました。来月1日にリセットされます。お急ぎの用件は、恐れ入りますが役員へ直接ご連絡をお願いいたします。"

        client = OpenAI(api_key=politician.openai_api_key.strip())
        
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        weekday_str = ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()]
        
        muni_name, dist_name, schedule_text = get_db_schedule_text()
        
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
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
                max_tokens=300, # 🛡️ トークン数を絞りコストを強制カット
            )
            
            # 🛡️ API通信が正常に成功した時のみ、利用回数を1カウント追加する
            if hasattr(politician, 'llm_quota'):
                politician.llm_quota.record_usage()
                
            return response.choices[0].message.content
            
        except openai.RateLimitError:
            # 🛡️ OpenAI側（プロジェクト機能等）で予算上限に達してAPIが遮断された場合
            return "【システム通知】当月のAI自動応答システムのご利用上限（予算設定）に達しました。来月リセットされるまでお待ちください。お急ぎの用件は役員へ直接ご連絡をお願いいたします。"
        except Exception as e: 
            print(f"OpenAI API Error for {politician.slug}: {e}")
            return "現在、AIシステムが混み合っております。しばらく経ってから再度お試しください。"

    @handler.add(FollowEvent)
    def handle_follow(event):
        line_user_id = event.source.user_id
        member, _ = AiMember.objects.get_or_create(
            line_user_id=line_user_id,
            defaults={'politician': politician}
        )
        member.registration_step = 0
        
        try:
            profile = line_bot_api.get_profile(line_user_id)
            member.line_display_name = profile.display_name
            member.line_picture_url = profile.picture_url  
        except Exception as e:
            print(f"プロフィール取得エラー: {e}")
            
        member.save()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"【{politician.name}】へようこそ！\nお名前（姓名）を入力してください。\n※姓と名の間にスペースを入れてくださいね。"))

    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event):
        try:
            user_text = event.message.text.strip()
            line_user_id = event.source.user_id
            member, _ = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={'politician': politician}
            )

            # 1. 登録フロー
            if member.registration_step < 3:
                if member.registration_step == 0 or member.registration_step == 1:
                    if " " not in user_text and "　" not in user_text:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="姓と名の間にスペースを入れて、もう一度お名前を入力してください。（例：宮崎 太郎）"))
                        return
                    
                    member.real_name = user_text
                    member.registration_step = 2 
                    member.save()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ありがとうございます。\n次に、班名（〇〇班）または部屋番号をお願いします。"))
                    return

                elif member.registration_step == 2:
                    member.address = user_text
                    member.registration_step = 3 # 登録完了
                    member.save()
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="登録完了！メニューからご活用ください。"))
                    return

            # ゴミ出しカレンダー
            if user_text == "ゴミ出しカレンダー":
                flex_msg = get_flex_schedule()
                line_bot_api.reply_message(event.reply_token, flex_msg)
                return
            
            # ポータルサイトへの誘導
            if user_text in ["ホームページ", "ホームページへ移動", "ポータルサイト"]:
                portal_url = f"https://jichidantai.jp/p/{politician.slug}/?openExternalBrowser=1"
                
                reply_text = (
                    f"🌐 {politician.name}の公式ページはこちらです！\n\n"
                    f"回覧板・アンケートの回答や、最新のお知らせは以下のリンクからご確認ください。\n\n"
                    f"{portal_url}"
                )
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return            
            
            # 行事カレンダー（カルーセル表示）
            if user_text == "行事カレンダー":
                today = timezone.localtime(timezone.now()).date()
                
                upcoming_events = Event.objects.filter(
                    politician=politician,
                    date__date__gte=today 
                ).order_by('date')[:3]

                if not upcoming_events.exists():
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="現在、予定されている直近の行事・イベントはありません。")
                    )
                    return

                columns = []
                for ev in upcoming_events:
                    card_title = ev.title[:40] if ev.title else "名称未設定"

                    local_date = timezone.localtime(ev.date)
                    date_str = f"{local_date.month}月{local_date.day}日 {local_date.strftime('%H:%M')}"

                    card_desc = ev.description if ev.description else "詳細はタップして確認"
                    text_content = f"📅 {date_str}\n{card_desc}"
                    if len(text_content) > 60:
                        text_content = text_content[:57] + "..."

                    columns.append(
                        CarouselColumn(
                            title=card_title,
                            text=text_content,
                            actions=[
                                PostbackAction(
                                    label='確認する',
                                    data=f'action=view_event&event_id={ev.id}'
                                )
                            ]
                        )
                    )

                carousel_message = TemplateSendMessage(
                    alt_text='直近の行事カレンダーが届きました',
                    template=CarouselTemplate(columns=columns)
                )

                line_bot_api.reply_message(event.reply_token, carousel_message)
                return

            # お問い合わせ
            if user_text == "お問い合わせ":
                contact_email = "winwinmiyazaki@miyazaki-catv.ne.jp" 
                msg = f"ご不明な点やご相談は、以下のメールアドレスまでお気軽にお問い合わせください。\n\n✉️ {contact_email}\n\n※送信の際は、お名前と地区名を添えていただけますとスムーズです。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
                return

            # 教材一覧の表示（カルーセル）
            if user_text in ["案内一覧", "教材一覧", "ルール確認"]:
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

            # 学習（案内）のサイクル処理
            if user_text.startswith("教材開始:") or user_text.startswith("教材進捗:") or user_text.startswith("教材次へ:") or user_text.startswith("教材終了:") or user_text.startswith("教材復習:"):
                parts = user_text.split(":")
                action = parts[0]
                title = parts[1]
                
                course = Course.objects.filter(title=title).first()
                if not course:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="情報が見つかりませんでした。"))
                    return

                progress, _ = UserProgress.objects.get_or_create(
                    line_user_id=line_user_id,
                    current_course=course,
                    defaults={'politician': politician, 'last_completed_order': 0}
                )

                if action == "教材終了":
                    reply_text = f"☕ ご確認お疲れ様でした！\n『{course.title}』の続きは、メニューからいつでも再開できます。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

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

                if action == "教材開始" or action == "教材次へ":
                    next_content = CourseContent.objects.filter(
                        course=course,
                        order__gt=progress.last_completed_order
                    ).order_by('order').first()

                    if next_content:
                        msg_text = f"📖 【{next_content.title}】\n\n{next_content.message_text}"
                        if next_content.video_url:
                            msg_text += f"\n\n🎬 参考動画はこちら:\n{next_content.video_url}"
                        
                        text_msg = TextSendMessage(text=msg_text)
                        
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

            # ▼ AI応答
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=get_ai_response(user_text)))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"エラー: {str(e)}"))

    @handler.add(PostbackEvent)
    def handle_postback(event):
        try:
            line_user_id = event.source.user_id
            postback_data = event.postback.data
            
            member, _ = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={'politician': politician}
            )
            
            data_dict = dict(parse_qsl(postback_data))
            
            if data_dict.get('action') == 'emergency':
                event_id = data_dict.get('event_id')
                ans_num = data_dict.get('ans')
                
                em_event = EmergencyEvent.objects.filter(id=event_id, politician=politician).first()
                if not em_event:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートは存在しないか、削除されました。"))
                    return
                if not em_event.is_active:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートの受付はすでに終了しています。"))
                    return
                
                answer_text = ""
                if ans_num == '1': answer_text = em_event.choice_1
                elif ans_num == '2': answer_text = em_event.choice_2
                elif ans_num == '3': answer_text = em_event.choice_3
                
                response_obj, created = EmergencyResponse.objects.update_or_create(
                    event=em_event,
                    ai_member=member,
                    defaults={'answer': answer_text}
                )
                
                reply_msg = f"「{answer_text}」として回答を記録しました。\nご協力ありがとうございます。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

            elif data_dict.get('action') == 'city_emergency':
                event_id = data_dict.get('event_id')
                ans_num = data_dict.get('ans')
                
                city_event = CityEmergencyEvent.objects.filter(id=event_id).first()
                if not city_event:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートは存在しないか、削除されました。"))
                    return
                if not city_event.is_active:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートの受付はすでに終了しています。"))
                    return
                
                answer_text = ""
                if ans_num == '1': answer_text = city_event.choice_1
                elif ans_num == '2': answer_text = city_event.choice_2
                elif ans_num == '3': answer_text = city_event.choice_3
                
                CityEmergencyResponse.objects.update_or_create(
                    event=city_event,
                    ai_member=member,
                    defaults={'answer': answer_text}
                )
                
                reply_msg = f"「{answer_text}」として回答を記録しました。\n行政からのアンケート・安否確認へのご協力ありがとうございます。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"エラーが発生しました: {str(e)}"))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")

def public_tenant_page(request, slug):
    """自治会ポータルサイトのメインビュー（統合・完成版）"""
    politician = get_object_or_404(Politician, slug=slug)

    if not hasattr(politician, 'page_config') or not politician.page_config.is_public:
        raise Http404("このページは現在準備中、または非公開です。")

    config = politician.page_config

    library_docs = []
    announcements = []
    upcoming_events = []

    if config.show_library:
        library_docs = LibraryDocument.objects.filter(
            politician=politician, is_deleted=False, access_level='PUBLIC'
        ).order_by('-fiscal_year', '-created_at')[:5]

    if config.show_announcements:
        announcements = Announcement.objects.filter(
            politician=politician, is_active=True
        ).order_by('-created_at')[:5]

    if config.show_events:
        now = timezone.now()
        upcoming_events = Event.objects.filter(
            politician=politician,
            date__gte=now
        ).order_by('date')[:5]

    active_surveys = Survey.objects.filter(
        politician=politician, is_active=True
    ).order_by('deadline')

    today = timezone.localtime(timezone.now()).date()
    target_area_ids = config.target_medical_areas.values_list('id', flat=True)

    duty_clinics = []
    if target_area_ids:
        upcoming_dates = HolidayDutySchedule.objects.filter(
            date__gte=today,
            institution__is_active=True,
            institution__area__in=target_area_ids
        ).order_by('date').values_list('date', flat=True).distinct()[:2]

        if upcoming_dates:
            duty_clinics = HolidayDutySchedule.objects.filter(
                date__in=upcoming_dates,
                institution__is_active=True,
                institution__area__in=target_area_ids
            ).select_related('institution').order_by(
                'date', 
                'institution__department', 
                'institution__name_kana'
            )

    target_mun_ids = config.target_condolence_areas.values_list('id', flat=True)
    condolences = []
    if target_mun_ids:
        two_days_ago = timezone.now() - timedelta(days=2)
        condolences = Condolence.objects.filter(
            funeral_hall__municipality__id__in=target_mun_ids
        ).filter(
            Q(funeral_datetime__gte=two_days_ago) | Q(funeral_datetime__isnull=True)
        ).select_related('funeral_hall').order_by('-funeral_datetime')

    _, last_day = calendar.monthrange(today.year, today.month)
    first_date_of_month = today.replace(day=1)
    last_date_of_month = today.replace(day=last_day)

    monthly_garbages_qs = GarbageCalendar.objects.filter(
        municipality=politician.gomi_municipality,
        district=politician.gomi_district,
        collection_date__gte=first_date_of_month,
        collection_date__lte=last_date_of_month
    ).order_by('collection_date')

    grouped_garbages = {}
    for g in monthly_garbages_qs:
        if g.collection_date not in grouped_garbages:
            grouped_garbages[g.collection_date] = []
        grouped_garbages[g.collection_date].append(g.garbage_type)

    calendar_data = []
    for d, types in grouped_garbages.items():
        calendar_data.append({
            'date': d,
            'types_str': '、'.join(types),
            'types_quoted': '「' + '」「'.join(types) + '」'
        })

    today_garbage = next((item for item in calendar_data if item['date'] == today), None)

    context = {
        'politician': politician,
        'config': config,
        'library_docs': library_docs,
        'announcements': announcements,
        'upcoming_events': upcoming_events,
        'active_surveys': active_surveys,
        'duty_clinics': duty_clinics,
        'today': today,
        'condolences': condolences,
        'today_garbage': today_garbage,
        'calendar_data': calendar_data, 
    }
    
    return render(request, 'bot/tenant_page.html', context)

@login_required
def minutes_support_page(request):
    """議事録作成サポートキットの案内画面"""
    expert_prompt = """
あなたは優秀な自治会の書記です。以下の会議録音テキストから、議事録のドラフトを作成してください。

【抽出条件】
1. 「決定事項」「保留事項」「次回の課題」を箇条書きで明確にすること。
2. 個人への誹謗中傷や、感情的な発言は除外すること。
3. 文体は「だ・である」調で、簡潔かつ客観的な記録とすること。

【会議録音テキスト】
（※ここにWhisperDesktopで文字起こししたテキストを貼り付けてください）
    """.strip()

    context = {
        'expert_prompt': expert_prompt,
    }
    return render(request, 'bot/minutes_support.html', context)
