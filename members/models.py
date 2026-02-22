from django.db import models

class AiMember(models.Model):
    """
    自治会 メンバー（住民）モデル
    LINEユーザーIDを主キーとして、属性情報を保持する
    """
    line_user_id = models.CharField(
        max_length=255, 
        primary_key=True, 
        verbose_name="LINEユーザーID"
    )
    display_name = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name="LINE表示名"
    )
    real_name = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name="氏名（本人申告）"
    )
    address = models.TextField(
        blank=True, 
        verbose_name="住所"
    )
    phone_number = models.CharField(
        max_length=20, 
        blank=True, 
        verbose_name="電話番号"
    )
    
    # 既存自治会名簿との紐付け用
    existing_member_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        verbose_name="既存名簿ID（手動照合用）"
    )
    is_approved = models.BooleanField(
        default=False, 
        verbose_name="自治会加入承認フラグ"
    )
    
    # 学習レベル管理
    LEVEL_CHOICES = [
        ('beginner', '初心者'),
        ('intermediate', '中級者'),
        ('advanced', '上級者'),
    ]
    current_level = models.CharField(
        max_length=20, 
        choices=LEVEL_CHOICES, 
        default='beginner', 
        verbose_name="AIスキルレベル"
    )

    # 初回登録の進行度を管理するステータス
    registration_step = models.IntegerField(
        default=0,
        verbose_name="登録ステップ",
        help_text="0:案内前, 1:名前待ち, 2:住所待ち, 3:登録完了"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.real_name or self.display_name or self.line_user_id

    class Meta:
        verbose_name = "住民（メンバー）"
        verbose_name_plural = "住民（メンバー）一覧"
        