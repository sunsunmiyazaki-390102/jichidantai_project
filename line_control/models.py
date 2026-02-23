from django.db import models

class LineSetting(models.Model):
    name = models.CharField(max_length=100, verbose_name="設定名", default="デフォルト")
    channel_secret = models.CharField(max_length=100, verbose_name="チャネルシークレット")
    channel_access_token = models.CharField(max_length=500, verbose_name="アクセストークン")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新日時")

    class Meta:
        verbose_name = "LINE連携設定"
        verbose_name_plural = "LINE連携設定"

    def __str__(self):
        return self.name
    