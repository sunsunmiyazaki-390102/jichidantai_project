from django.db import models
from django.utils import timezone

def library_directory_path(instance, filename):
    """
    S3への自動ルーティング関数
    保存先例: tenant_1/library/GENERAL/2026_soukai.pdf
    """
    # 紐付いている自治会(Politician)のIDを取得
    p_id = getattr(instance, 'politician_id', 'unknown')
    return f'tenant_{p_id}/library/{instance.category}/{filename}'

class ActiveDocumentManager(models.Manager):
    """論理削除されたデータを絶対に取得させないための専用マネージャー"""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

class LibraryDocument(models.Model):
    """自治会の過去資料・議事録などをS3で永続保管する書庫モデル"""

    # --- 権限マトリクス定義 ---
    ACCESS_LEVELS = (
        ('PUBLIC', '全住民公開'),
        ('BOARD', '役員のみ'),
        ('ADMIN', 'システム管理者のみ'),
    )

    # --- カテゴリ定義 ---
    CATEGORIES = (
        ('GENERAL', '総会資料'),
        ('BOARD', '役員会議事録'),
        ('NOTICE', '回覧板・お知らせ'),
        ('ACCOUNTING', '会計・決算報告'),
        ('DISASTER', '防災マニュアル'),
        ('OTHER', 'その他'),
    )

    # 既存の設計に合わせたリレーション（botアプリのPoliticianモデルを参照）
    politician = models.ForeignKey(
        'bot.Politician', 
        on_delete=models.CASCADE, 
        verbose_name='対象自治会'
    )
    
    title = models.CharField('資料タイトル', max_length=255)
    fiscal_year = models.IntegerField('対象年度', default=timezone.now().year)
    category = models.CharField('カテゴリ', max_length=20, choices=CATEGORIES)
    
    # S3へアップロードされるファイルフィールド
    document_file = models.FileField(
        'ファイル (PDF等)', 
        upload_to=library_directory_path,
        help_text="※10MB以下のPDFまたは画像ファイルを推奨"
    )

    # セキュリティ・運用メタデータ
    access_level = models.CharField('アクセス権限', max_length=10, choices=ACCESS_LEVELS, default='BOARD')
    is_deleted = models.BooleanField('削除フラグ(論理削除)', default=False)
    
    created_at = models.DateTimeField('登録日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True)

    # マネージャーの切り替え（運用上の事故防止）
    objects = models.Manager()              # 管理画面用（全件表示）
    active_objects = ActiveDocumentManager()  # 住民画面用（削除済みを隠蔽）

    class Meta:
        verbose_name = 'ライブラリ資料'
        verbose_name_plural = 'ライブラリ資料一覧'
        ordering = ['-fiscal_year', '-created_at'] # 最新年度の新しい順に表示
        
        # 運営側の防衛的視点: PostgreSQLの検索負荷を極限まで下げる複合インデックス
        indexes = [
            models.Index(fields=['politician', 'category', 'fiscal_year']),
            models.Index(fields=['politician', 'access_level', 'is_deleted']),
        ]

    def __str__(self):
        return f"[{self.fiscal_year}年度] {self.title} ({self.politician.name})"

    # 物理削除を強制ブロックし、論理削除へ変換
    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.save()
