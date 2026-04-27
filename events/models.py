from django.db import models
import uuid

class Event(models.Model):
    politician = models.ForeignKey(
        'bot.Politician',
        on_delete=models.CASCADE,
        verbose_name='対象自治会',
        null=True,
        blank=True,
        related_name='events_app_events'
    )    
    title = models.CharField("イベント名", max_length=100)
    start_time = models.DateTimeField("開始日時")
    location = models.CharField("場所", max_length=100, default="未定")
    description = models.TextField("詳細・案内文", blank=True, null=True)
    
    # 既存の関連URL（イベントの告知ページなど）
    url = models.URLField("関連URL", blank=True, null=True)
    
    # --- 今回追加するフィールド（動画URL） ---
    video_url = models.URLField(
        "動画URL", 
        max_length=200, 
        blank=True, 
        null=True, 
        help_text="YouTubeなどの動画URLを入力してください"
    )
    # ----------------------------------------
    
    is_active = models.BooleanField("公開中", default=True)

    def __str__(self):
        return f"{self.title} ({self.start_time.strftime('%Y-%m-%d')})"

    class Meta:
        verbose_name = "イベント情報"
        verbose_name_plural = "イベント情報一覧"

# 運営側の防衛的視点：マルチテナント用フォルダ分離ロジック
def tenant_directory_path(instance, filename):
    # 本番運用時は instance.tenant.id 等で自治会ごとに動的ルーティングします。
    # 今回はテスト用に 'test_tenant_001' という固定フォルダを切ります。
    tenant_id = getattr(instance, 'tenant_id', 'test_tenant_001')
    return f'{tenant_id}/photos/{filename}'

 # 運営側の防衛的視点: 本番環境用のテナント別ルーティングへ修正
def event_photo_path(instance, filename):
    # テスト用の 'test_tenant_001' をやめ、実際の自治会IDを取得
    p_id = getattr(instance, 'politician_id', 'unknown')
    return f'tenant_{p_id}/event_photos/{filename}'

class EventPhoto(models.Model):
    # ▼ 本番仕様として、自治会への紐付け（リレーション）を追加
    politician = models.ForeignKey(
        'bot.Politician', 
        on_delete=models.CASCADE, 
        verbose_name='対象自治会'
    )
    
    title = models.CharField('写真タイトル', max_length=255)
    image = models.ImageField('イベント写真', upload_to=event_photo_path)
    uploaded_at = models.DateTimeField('アップロード日時', auto_now_add=True)

    class Meta:
        # 「(S3テスト)」という文字を外し、本番の名称へ変更
        verbose_name = 'イベント写真'
        verbose_name_plural = 'イベント写真一覧'

    def __str__(self):
        # どの自治会の写真か管理画面で分かりやすいように変更
        return f"{self.title} ({self.politician.name})"

class Announcement(models.Model):
    """自治会からのお知らせ（回覧板のデジタル版）"""
    politician = models.ForeignKey(
        'bot.Politician',
        on_delete=models.CASCADE,
        related_name='announcements'
    )
    title = models.CharField("タイトル", max_length=200)
    content = models.TextField("内容")
    created_at = models.DateTimeField("投稿日時", auto_now_add=True)
    is_active = models.BooleanField("公開中", default=True)

    class Meta:
        verbose_name = "お知らせ"
        verbose_name_plural = "お知らせ一覧"

class Survey(models.Model):
    """自治会の回覧板・アンケート本体"""
    politician = models.ForeignKey(
        'bot.Politician', on_delete=models.CASCADE, related_name='surveys', verbose_name='対象自治会'
    )
    title = models.CharField("タイトル（例：総会出欠確認）", max_length=200)
    description = models.TextField("説明文・案内", blank=True)
    deadline = models.DateTimeField("回答締切日時")
    is_active = models.BooleanField("回答受付中", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "アンケート・回覧板"
        verbose_name_plural = "アンケート・回覧板一覧"

    def __str__(self):
        return f"[{self.politician.name}] {self.title}"

class SurveyResponse(models.Model):
    """住民からの回答データ"""
    ATTENDANCE_CHOICES = [
        ('出席_賛成', '出席（または賛成）'),
        ('欠席_反対', '欠席（または反対）'),
        ('未定_保留', '未定（または保留）'),
    ]
    
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name='responses')
    respondent_name = models.CharField("回答者名（世帯主・班など）", max_length=100)
    attendance = models.CharField("出欠・賛否", max_length=20, choices=ATTENDANCE_CHOICES, blank=True, null=True)
    comment = models.TextField("ご意見・自由記述", blank=True)
    
    # 🛡️ 運営側の防衛的視点: 重複回答による集計の混乱を防ぐための追跡フィールド
    session_key = models.CharField("ブラウザセッションID", max_length=100, blank=True)
    ip_address = models.GenericIPAddressField("IPアドレス", blank=True, null=True)
    submitted_at = models.DateTimeField("回答日時", auto_now_add=True)

    class Meta:
        verbose_name = "回答データ"
        verbose_name_plural = "回答データ一覧"
        
        # 🛡️ データベース駆動の防衛: 同一ブラウザから同一アンケートへの複数回送信をDBレベルでブロック
        constraints = [
            models.UniqueConstraint(fields=['survey', 'session_key'], name='unique_survey_response')
        ]

    def __str__(self):
        return f"{self.respondent_name} - {self.attendance}"
