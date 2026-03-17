from django.db import models
from bot.models import Politician

class AiMember(models.Model):
    """
    自治会 メンバー（住民）モデル（運営側管理）
    LINEユーザー情報を保持する
    """
    # ★追加: マルチテナント（所属団体）
    politician = models.ForeignKey(
        Politician, 
        on_delete=models.CASCADE, 
        verbose_name="所属団体",
        null=True, blank=True # 既存データ保護のため一旦null許可
    )

    # ★変更: primary_key=True を外し、通常のフィールドに変更
    line_user_id = models.CharField(
        max_length=255, 
        verbose_name="LINEユーザーID"
    )
    
    # 既存フィールド群
    display_name = models.CharField(max_length=100, blank=True, verbose_name="LINE表示名")
    real_name = models.CharField(max_length=100, blank=True, verbose_name="氏名（本人申告）")
    address = models.TextField(blank=True, verbose_name="班名（部屋番号）")
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="電話番号")

    line_display_name = models.CharField("LINE登録名", max_length=255, blank=True, null=True)
    line_picture_url = models.URLField("LINEアイコン画像URL", max_length=1000, blank=True, null=True)    
    
    existing_member_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="既存名簿ID（手動照合用）")
    is_approved = models.BooleanField(default=False, verbose_name="自治会加入承認フラグ")
    
    LEVEL_CHOICES = [
        ('beginner', '初心者'),
        ('intermediate', '中級者'),
        ('advanced', '上級者'),
    ]
    current_level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='beginner', verbose_name="AIスキルレベル")

    registration_step = models.IntegerField(
        default=0,
        verbose_name="登録ステップ",
        help_text="0:案内前, 1:名前待ち, 2:住所待ち, 3:登録完了"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.real_name or '未入力'} ({self.line_display_name or '名無し'})"

    class Meta:
        verbose_name = "住民（メンバー）"
        verbose_name_plural = "住民（メンバー）一覧"
        # ★追加: 1つの団体に同じLINE IDが2つ以上登録されるのを防ぐ
        unique_together = ('politician', 'line_user_id')


# ★新規追加: 団体側が管理・CSV入出力する名簿テーブル
class TenantMemberProfile(models.Model):
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="所属団体")
    
    # 運営側のデータ（AiMember）と紐づける（未登録の住民も名簿化できるよう null=True にする）
    ai_member = models.OneToOneField(
        AiMember, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='profile', verbose_name="紐づくLINEアカウント"
    )
    
    # 団体側が自由に管理する基本情報
    management_id = models.CharField("管理番号", max_length=50)
    official_name = models.CharField("氏名", max_length=100)

    # ▼▼▼ 新規追加：電話番号の箱 ▼▼▼
    phone_number = models.CharField("電話番号", max_length=20, blank=True, null=True)

    official_address = models.CharField("住所", max_length=255, blank=True, null=True)
    birth_date = models.DateField("生年月日", blank=True, null=True)
    head_of_household = models.CharField("世帯主名", max_length=100, blank=True, null=True)
    relationship = models.CharField("世帯主との続柄", max_length=50, blank=True, null=True)

    # 団体ごとに名称を変えられる汎用カスタムフィールド（各3個）
    group_1 = models.CharField("グループ1", max_length=100, blank=True, null=True)
    group_2 = models.CharField("グループ2", max_length=100, blank=True, null=True)
    group_3 = models.CharField("グループ3", max_length=100, blank=True, null=True)
    note_1 = models.CharField("備考1", max_length=255, blank=True, null=True)
    note_2 = models.CharField("備考2", max_length=255, blank=True, null=True)
    note_3 = models.CharField("備考3", max_length=255, blank=True, null=True)   

    # ▼▼▼ 新規追加：テーブル名を綺麗な日本語にする ▼▼▼
    class Meta:
        verbose_name = "自治会名簿（メンバーデータ）"
        verbose_name_plural = "自治会名簿（メンバーデータ）"
        