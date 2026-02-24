from django.db import models
from members.models import AiMember

# --------------------------------------------------
# 1. 既存モデル：会話ログ
# --------------------------------------------------
class MessageLog(models.Model):
    """
    LINEでのやり取りをすべて記録するモデル
    """
    ROLE_CHOICES = [
        ('user', '利用者'),
        ('assistant', 'AIアシスタント'),
        ('system', 'システム'),
    ]

    member = models.ForeignKey(
        AiMember, 
        on_delete=models.CASCADE, 
        related_name='message_logs',
        verbose_name="メンバー"
    )
    role = models.CharField(
        max_length=10, 
        choices=ROLE_CHOICES, 
        verbose_name="送信者"
    )
    text = models.TextField(verbose_name="メッセージ内容")
    is_escalated = models.BooleanField(
        default=False, 
        verbose_name="相談窓口へ転送"
    )
    tokens = models.IntegerField(default=0, verbose_name="消費トークン数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="送信日時")

    class Meta:
        verbose_name = "会話ログ"
        verbose_name_plural = "会話ログ一覧"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.member.display_name}: {self.text[:20]}"

# --------------------------------------------------
# 2. 新設モデル：自治会（テナント）管理
# --------------------------------------------------
class Politician(models.Model):
    """自治会（テナント）情報を管理"""
    name = models.CharField("自治会名", max_length=100)
    line_channel_secret = models.CharField("Channel Secret", max_length=255)
    line_access_token = models.CharField("Access Token", max_length=255)
    slug = models.SlugField("識別パス", unique=True, help_text="URLの一部になります")

    # --- ゴミ収集地区の設定 ---
    GOMI_REGION_CHOICES = [
        ('miyazaki_kita_a', '宮崎市：北A地区'),
        ('miyazaki_kita_b', '宮崎市：北B地区'),
        ('miyazaki_minami_a', '宮崎市：南A地区'),
        ('miyazaki_minami_b', '宮崎市：南B地区'),
        ('none', '設定なし（または他市区町村）'),
    ]
    gomi_region = models.CharField(
        max_length=50,
        choices=GOMI_REGION_CHOICES,
        default='none',
        verbose_name="ゴミ収集地区グループ",
        help_text="この自治会が該当するゴミ収集地区を選択してください。"
    )

    # --- AI関連の設定フィールド ---
    openai_api_key = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name="OpenAI APIキー"
    )
    system_prompt = models.TextField(
        default="あなたは親切な自治会のアシスタントです。住民の質問に丁寧な言葉で答えてください。",
        verbose_name="AIシステムプロンプト"
    )
    ai_model_name = models.CharField(
        max_length=50, 
        default="gpt-4o-mini", 
        verbose_name="使用モデル名"
    )
    
    openai_assistant_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        verbose_name="OpenAI アシスタントID",
        help_text="Assistants APIを使用する場合は asst_ から始まるIDを入力してください"
    )

    class Meta:
        verbose_name = "自治会"
        verbose_name_plural = "自治会一覧"

    def __str__(self):
        return self.name

# --------------------------------------------------
# 3. 既存モデル：活動予定
# --------------------------------------------------
class Event(models.Model):
    """自治会ごとの活動予定"""
    politician = models.ForeignKey(
        Politician, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        verbose_name="担当自治会"
    )
    title = models.CharField("イベント名", max_length=200)
    date = models.DateTimeField("開催日時")

    class Meta:
        verbose_name = "活動予定"
        verbose_name_plural = "活動予定一覧"

    def __str__(self):
        return self.title

# --------------------------------------------------
# 4. 新設モデル：教材配信・進捗管理
# --------------------------------------------------
class Course(models.Model):
    """AI初心者、中級者などのコース"""
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="担当自治会")
    title = models.CharField("コース名", max_length=100)
    description = models.TextField("コース説明", blank=True)
    video_url = models.URLField("動画URL", max_length=500, blank=True, null=True, help_text="YouTubeなどの動画URLを入力してください")

    class Meta:
        verbose_name = "教材コース"
        verbose_name_plural = "教材コース一覧"

    def __str__(self):
        return f"{self.politician.name} - {self.title}"
    
class CourseContent(models.Model):
    """各コース内の具体的な教材（第1回、第2回...）"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='contents', verbose_name="コース")
    order = models.PositiveIntegerField("配信順序")
    title = models.CharField("教材タイトル", max_length=200)
    video_url = models.URLField("動画URL")
    message_text = models.TextField("解説文")

    class Meta:
        verbose_name = "教材コンテンツ"
        verbose_name_plural = "教材コンテンツ一覧"
        ordering = ['order']
        unique_together = ('course', 'order')

    def __str__(self):
        return f"[{self.order}] {self.title}"

class UserProgress(models.Model):
    """会員（LINEユーザー）の学習進捗"""
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="担当自治会")
    line_user_id = models.CharField("LINE ID", max_length=100)
    current_course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, verbose_name="受講中のコース")
    last_completed_order = models.PositiveIntegerField("完了済み順序", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "受講進捗"
        verbose_name_plural = "受講進捗一覧"
        unique_together = ('line_user_id', 'current_course')
        