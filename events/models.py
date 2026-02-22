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