from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent, FlexSendMessage
from django.utils import timezone
from openai import OpenAI
import json
import traceback
import time

from .models import Politician, Event, Course, CourseContent, UserProgress
from members.models import AiMember

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

        # .envの古い設定を強制的に無視し、カギだけを信じる
        client = OpenAI(
            api_key=api_key,
            organization=None,
            project=None,
            default_headers={"OpenAI-Beta": "assistants=v2"}
        )

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
                    assistant_id=assistant_id
                )
                while run.status in ['queued', 'in_progress']:
                    time.sleep(1)
                    run = client.beta.threads.runs.retrieve(
                        thread_id=thread.id,
                        run_id=run.id
                    )
                if run.status == 'completed':
                    messages = client.beta.threads.messages.list(thread_id=thread.id)
                    for msg in messages.data:
                        if msg.role == "assistant":
                            answer_text = msg.content[0].text.value
                            import re
                            clean_text = re.sub(r'【.*?】', '', answer_text)
                            return clean_text
                else:
                    return f"AIの処理が失敗しました。ステータス: {run.status}"

            except Exception as e:
                key_hint = api_key[:15] + "..."
                return f"⚠️ APIエラー\n\n【認識しているカギ】\n{key_hint}\n\n【認識しているID】\n{assistant_id}\n\n【エラー詳細】\n{str(e)}"

        else:
            try:
                response = client.chat.completions.create(
                    model=politician.ai_model_name,
                    messages=[
                        {"role": "system", "content": politician.system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    max_tokens=500
                )
                return response.choices[0].message.content
            except Exception as e:
                return f"AIが応答できませんでした。エラー: {str(e)}"

    @handler.add(MessageEvent, message=TextMessage)
    def handle_text_message(event):
        try:
            user_text = event.message.text.strip()
            line_user_id = event.source.user_id
            
            member, created = AiMember.objects.get_or_create(
                line_user_id=line_user_id,
                defaults={
                    'display_name': '未設定',
                    'real_name': '',
                    'address': '',
                    'phone_number': ''
                }
            )

            # --- 初回登録（住民名簿連携） ---
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
                reply_text = "登録が完了しました！\nこれよりすべての機能をご利用いただけます✨\n\nメニューから自治会のルールを確認したり、ゴミ出しについて質問したりしてみてください。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return
            
            # --- 自治会の案内・ルール表示 ---
            if user_text in ["教材一覧", "教材コース一覧", "案内一覧", "ルール確認"]:
                courses = Course.objects.filter(politician=politician).order_by('id')
                
                if not courses.exists():
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="現在、ご案内情報は準備中です。"))
                    return

                contents = []
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
                                {
                                    "type": "button", "style": "primary", "color": "#1DB446",
                                    "action": {"type": "message", "label": "確認する", "text": f"教材開始:{course.title}"}
                                }
                            ]
                        }
                    }
                    contents.append(bubble)

                flex_message = FlexSendMessage(alt_text="案内一覧", contents={"type": "carousel", "contents": contents})
                line_bot_api.reply_message(event.reply_token, flex_message)
                return

            # --- 案内・ルール関連の処理 ---
            elif user_text.startswith("教材開始:") or user_text.startswith("教材進捗:") or user_text.startswith("教材次へ:") or user_text.startswith("教材終了:") or user_text.startswith("教材復習:"):
                parts = user_text.split(":")
                action = parts[0]
                title = parts[1]
                
                course = Course.objects.filter(politician=politician, title=title).first()
                if not course:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="案内が見つかりませんでした。"))
                    return

                progress, created = UserProgress.objects.get_or_create(
                    politician=politician,
                    line_user_id=line_user_id,
                    current_course=course,
                    defaults={'last_completed_order': 0}
                )

                if action == "教材終了":
                    reply_text = f"☕ ご確認ありがとうございました！\n『{course.title}』の続きは、メニューからいつでも再開できます。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                if action == "教材復習":
                    completed_contents = CourseContent.objects.filter(
                        course=course,
                        order__lte=progress.last_completed_order
                    ).order_by('order')

                    if not completed_contents:
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="まだ見返せる案内がありません。まずは確認を進めましょう！"))
                        return
                    
                    reply_text = f"📚 『{course.title}』の確認リストです\n\n"
                    for content in completed_contents:
                        reply_text += f"第{content.order}回：{content.title}\n🎬 {content.video_url}\n\n"
                    
                    reply_text += "何度でも見返して、ルールを確認しましょう✨"
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
                                    {"type": "text", "text": "✅ 確認記録を保存しました", "weight": "bold", "color": "#1DB446", "size": "md"},
                                    {"type": "text", "text": "続けて次の案内を確認しますか？", "wrap": True, "size": "sm", "margin": "md"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "vertical", "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button", "style": "primary", "color": "#1DB446",
                                        "action": {"type": "message", "label": "次の案内へ進む", "text": f"教材次へ:{course.title}"}
                                    },
                                    {
                                        "type": "button", "style": "secondary",
                                        "action": {"type": "message", "label": "確認を一旦終了する", "text": f"教材終了:{course.title}"}
                                    }
                                ]
                            }
                        }
                        flex_msg = FlexSendMessage(alt_text="次の案内に進みますか？", contents=bubble)
                        line_bot_api.reply_message(event.reply_token, flex_msg)
                    else:
                        reply_text = f"🎉 ありがとうございます！\n『{course.title}』の全項目の確認が完了しました！\n引き続き、他の案内もご確認ください✨"
                        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                if action == "教材開始" or action == "教材次へ":
                    next_content = CourseContent.objects.filter(
                        course=course,
                        order__gt=progress.last_completed_order
                    ).order_by('order').first()

                    if next_content:
                        text_msg = TextSendMessage(
                            text=f"📖 【{next_content.title}】\n\n{next_content.message_text}\n\n🎬 動画/詳細はこちら:\n{next_content.video_url}"
                        )
                        bubble = {
                            "type": "bubble",
                            "body": {
                                "type": "box", "layout": "vertical",
                                "contents": [
                                    {"type": "text", "text": "確認が終わったらボタンを押してください👇", "wrap": True, "size": "sm", "color": "#666666"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "horizontal", "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button", "style": "primary", "color": "#1DB446",
                                        "action": {"type": "message", "label": "確認完了", "text": f"教材進捗:{course.title}:{next_content.order}"}
                                    },
                                    {
                                        "type": "button", "style": "secondary",
                                        "action": {"type": "message", "label": "スキップ", "text": f"教材進捗:{course.title}:{next_content.order}"}
                                    }
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
                                    {"type": "text", "text": "🎉 全項目確認完了", "weight": "bold", "color": "#1DB446", "size": "md"},
                                    {"type": "text", "text": f"すでに『{course.title}』を最後まで確認済みです！ご協力ありがとうございます✨\n\n確認リストから過去の案内を再確認できます。", "wrap": True, "size": "sm", "margin": "md"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "vertical", "spacing": "sm",
                                "contents": [
                                    {
                                        "type": "button", "style": "primary", "color": "#1DB446",
                                        "action": {"type": "message", "label": "確認リストを見る", "text": f"教材復習:{course.title}"}
                                    }
                                ]
                            }
                        }
                        flex_msg = FlexSendMessage(alt_text="全項目確認完了", contents=bubble)
                        line_bot_api.reply_message(event.reply_token, flex_msg)
                    return

            # --- 行事予定 ---
            elif user_text == "行事予定" or user_text == "活動予定":
                future_event = Event.objects.filter(
                    politician=politician,
                    date__gte=timezone.now()
                ).order_by('date').first()

                if future_event:
                    dt = timezone.localtime(future_event.date)
                    time_str = f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour}:{dt.minute:02}"
                    reply_text = f"【行事予定】\n📛 {future_event.title}\n📅 {time_str}"
                else:
                    reply_text = "現在、予定されている行事はありません。"
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            # --- それ以外はAI対話 ---
            else:
                reply_text = get_ai_response(user_text)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

        except Exception as e:
            error_msg = traceback.format_exc()
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"⚠️システム内部エラーが発生しました\n\n【エラー内容】\n{str(e)}\n\n【詳細】\n{error_msg[:300]}")
            )

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        return HttpResponseBadRequest()
    return HttpResponse("OK")
