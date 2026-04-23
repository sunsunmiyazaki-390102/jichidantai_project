from django.db import models

class Event(models.Model):
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

class EventPhoto(models.Model):
    title = models.CharField('写真タイトル', max_length=255)
    image = models.ImageField('イベント写真', upload_to=tenant_directory_path)
    uploaded_at = models.DateTimeField('アップロード日時', auto_now_add=True)

    class Meta:
        verbose_name = 'イベント写真(S3テスト)'
        verbose_name_plural = 'イベント写真(S3テスト)'

    def __str__(self):
        return self.title
           