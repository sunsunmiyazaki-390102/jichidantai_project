from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Survey, SurveyResponse
from .forms import SurveyResponseForm

def survey_detail(request, survey_id):
    """アンケート回答画面と投稿処理"""
    survey = get_object_or_404(Survey, pk=survey_id, is_active=True)
    
    # 🛡️ 運営側の防衛的視点: セッションが存在しない場合は強制生成
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    # 🛡️ 二重投稿チェック
    already_responded = SurveyResponse.objects.filter(
        survey=survey, session_key=session_key
    ).exists()

    if request.method == 'POST':
        if already_responded:
            messages.error(request, "このアンケートには既に回答済みです。")
            return redirect('survey_detail', survey_id=survey.id)

        form = SurveyResponseForm(request.POST)
        if form.is_valid():
            response = form.save(commit=False)
            response.survey = survey
            response.session_key = session_key
            # IPアドレスの取得（ログ保存用）
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                response.ip_address = x_forwarded_for.split(',')[0]
            else:
                response.ip_address = request.META.get('REMOTE_ADDR')
            
            response.save()
            messages.success(request, "回答を送信しました。ご協力ありがとうございました。")
            return redirect('survey_detail', survey_id=survey.id)
    else:
        form = SurveyResponseForm()

    context = {
        'survey': survey,
        'form': form,
        'already_responded': already_responded,
    }
    return render(request, 'events/survey_detail.html', context)
