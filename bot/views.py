from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage, FollowEvent, PostbackEvent
from django.utils import timezone
from datetime import timedelta
from urllib.parse import parse_qsl
from openai import OpenAI
import time
import re
import traceback

from .models import Politician, Event, Course, CourseContent, UserProgress, CourseAssignment, GarbageCalendar, EmergencyEvent, EmergencyResponse, CityEmergencyEvent, CityEmergencyResponse
from members.models import AiMember

# 💡【削除】ここに書いてあった REGION_MAP は不要になったため完全に削除しました！

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
        
        # ★【変更】データベース（Politician）から直接「市町村」と「地区」を取り出す！
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

    # 💡【人間用】LINE画面に表示する美しいビジュアルカレンダー
    def get_flex_schedule():
        now_jst = timezone.localtime(timezone.now())
        today = now_jst.date()
        
        # ★【変更】データベース（Politician）から直接取り出す！
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

        # 日付を「文字列（YYYY-MM-DD）」に変換して確実にグループ化する
        grouped_schedules = {}
        for s in schedules:
            date_key = s.collection_date.strftime('%Y-%m-%d')
            if date_key not in grouped_schedules:
                grouped_schedules[date_key] = []
            grouped_schedules[date_key].append(s)

        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        contents = []
        
        # まとめられた日付ごとにループを回す
        for date_key, items in grouped_schedules.items():
            date_obj = items[0].collection_date
            w = weekdays[date_obj.weekday()]
            date_str = f"{date_obj.month}/{date_obj.day}({w})"
            
            # ゴミの種類を横並びにするためのテキスト（span）のリストを作成
            spans = []
            for i, item in enumerate(items):
                color = get_garbage_color(item.garbage_type)
                spans.append({"type": "span", "text": item.garbage_type, "color": color, "weight": "bold"})
                
                # 注意書きがあれば小さく追加
                if item.notes:
                    spans.append({"type": "span", "text": f"({item.notes})", "color": "#888888", "size": "xs"})
                
                # 最後のアイテムでなければ区切り文字（ / ）を入れる
                if i < len(items) - 1:
                    spans.append({"type": "span", "text": " / ", "color": "#CCCCCC"})
            
            # 1日分の行を作成
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
        
        # Windows特有の文字化けエラーを防ぐため、年月日の作り方を安全な形式に変更
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
        line_user_id = event.source.user_id
        member, _ = AiMember.objects.get_or_create(
            line_user_id=line_user_id,
            defaults={'politician': politician}
        )
        member.registration_step = 0
        
        # 💡【新規追加】友だち追加された瞬間にLINEプロフィールを自動取得！
        try:
            profile = line_bot_api.get_profile(line_user_id)
            member.line_display_name = profile.display_name # LINEの表示名を保存
            member.line_picture_url = profile.picture_url   # LINEのアイコン画像を保存
        except Exception as e:
            # 万が一、一瞬でブロックされた場合などはエラーを無視して進める
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
            
            # 誰がボタンを押したか特定（自動登録）
            member, _ = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={'politician': politician}
            )
            
            # 暗号（"action=emergency&event_id=1&ans=1"）を辞書型に解読する
            data_dict = dict(parse_qsl(postback_data))
            
            # 防災・アンケートの回答だった場合
            if data_dict.get('action') == 'emergency':
                event_id = data_dict.get('event_id')
                ans_num = data_dict.get('ans')
                
                # イベントが存在するか、受付中かを確認
                em_event = EmergencyEvent.objects.filter(id=event_id, politician=politician).first()
                if not em_event:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートは存在しないか、削除されました。"))
                    return
                if not em_event.is_active:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートの受付はすでに終了しています。"))
                    return
                
                # どのボタンが押されたかを判定
                answer_text = ""
                if ans_num == '1': answer_text = em_event.choice_1
                elif ans_num == '2': answer_text = em_event.choice_2
                elif ans_num == '3': answer_text = em_event.choice_3
                
                # データベースに記録（または上書き）する
                response_obj, created = EmergencyResponse.objects.update_or_create(
                    event=em_event,
                    ai_member=member,
                    defaults={'answer': answer_text}
                )
                
                # お礼のメッセージを返す
                reply_msg = f"「{answer_text}」として回答を記録しました。\nご協力ありがとうございます。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

            elif data_dict.get('action') == 'city_emergency':
                event_id = data_dict.get('event_id')
                ans_num = data_dict.get('ans')
                
                # 行政のイベントが存在するか、受付中かを確認
                city_event = CityEmergencyEvent.objects.filter(id=event_id).first()
                if not city_event:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートは存在しないか、削除されました。"))
                    return
                if not city_event.is_active:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="このアンケートの受付はすでに終了しています。"))
                    return
                
                # どのボタンが押されたかを判定
                answer_text = ""
                if ans_num == '1': answer_text = city_event.choice_1
                elif ans_num == '2': answer_text = city_event.choice_2
                elif ans_num == '3': answer_text = city_event.choice_3
                
                # 行政用の集計データベースに記録（または上書き）する
                CityEmergencyResponse.objects.update_or_create(
                    event=city_event,
                    ai_member=member,
                    defaults={'answer': answer_text}
                )
                
                # 少し丁寧なお礼のメッセージを返す
                reply_msg = f"「{answer_text}」として回答を記録しました。\n行政からのアンケート・安否確認へのご協力ありがとうございます。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

        except Exception as e:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"エラーが発生しました: {str(e)}"))

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")
