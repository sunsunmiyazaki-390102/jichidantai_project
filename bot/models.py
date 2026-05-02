from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import uuid
import os

class Politician(models.Model):
    name = models.CharField("自治会名", max_length=100)
    slug = models.SlugField("スラグ（URL用）", unique=True)
    line_channel_secret = models.CharField(max_length=255)
    line_access_token = models.TextField()
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)
    openai_assistant_id = models.CharField(max_length=255, blank=True, null=True)
    ai_model_name = models.CharField(max_length=50, default="gpt-4o")
    system_prompt = models.TextField(blank=True, null=True)
    gomi_municipality = models.CharField("ゴミ収集: 市町村", max_length=50, blank=True, null=True, help_text="例: 宮崎市")
    gomi_district = models.CharField("ゴミ収集: 地区", max_length=50, blank=True, null=True, help_text="例: 北B地区")

    # ▼ 今回追記する「市町村コード」
    city_code = models.CharField(
        "所属市町村コード", max_length=20, blank=True, null=True, 
        help_text="行政が横断管理するためのコード（例：宮崎市なら 45201 など）"
    ) 

    # ▼ 今回追記する「地区・町名コード」
    district_code = models.CharField(
        "所属地区・町名コード", max_length=50, blank=True, null=True, 
        help_text="市町村内のさらに細かいエリアコード（例：吉村町なら yoshimura など）"
    )       

    # --- [追加] テナント管理者（マルチテナント分離用） ---
    admin_users = models.ManyToManyField(
        User, 
        verbose_name="システム管理者", 
        blank=True, 
        related_name="managed_politicians",
        help_text="この自治会を管理できるユーザー（複数選択可）"
    )

    # --- 団体側カスタム項目のラベル定義（メタデータ駆動） ---
    label_group_1 = models.CharField("グループ1の名称", max_length=50, default="グループ1", help_text="例: 役職名")
    label_group_2 = models.CharField("グループ2の名称", max_length=50, default="グループ2", help_text="例: 所属班")
    label_group_3 = models.CharField("グループ3の名称", max_length=50, default="グループ3", help_text="例: 専門部会")
    
    label_note_1 = models.CharField("備考1の名称", max_length=50, default="備考1", help_text="例: 駐車場番号")
    label_note_2 = models.CharField("備考2の名称", max_length=50, default="備考2", help_text="例: 家族構成")
    label_note_3 = models.CharField("備考3の名称", max_length=50, default="備考3", help_text="例: 特記事項")

    # 中間テーブル経由の多対多関係
    courses = models.ManyToManyField('Course', through='CourseAssignment', blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "自治会"
        verbose_name_plural = "自治会一覧"    

class Course(models.Model):
    # politicianとの直接の紐付け（ForeignKey）を削除
    title = models.CharField("案内タイトル", max_length=200)
    description = models.TextField("説明", blank=True)
    video_url = models.URLField("紹介動画URL", blank=True, null=True)

    def __str__(self):
        return self.title
    class Meta:
        verbose_name = "案内・教材"
        verbose_name_plural = "案内・教材一覧"
        
# 新設：紐付け専用テーブル
class CourseAssignment(models.Model):
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ['order']
        verbose_name = "案内情報の割り当て"
        verbose_name_plural = "案内情報の割り当て"

class CourseContent(models.Model):
    course = models.ForeignKey(Course, related_name='contents', on_delete=models.CASCADE)
    order = models.PositiveIntegerField("順番")
    title = models.CharField("教材タイトル", max_length=200)
    message_text = models.TextField("メッセージ内容", blank=True)
    video_url = models.URLField("解説動画URL", blank=True, null=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.course.title} - {self.order}: {self.title}"

class Event(models.Model):
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    date = models.DateTimeField()

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "イベント・行事カレンダー"
        verbose_name_plural = "イベント・行事カレンダー"

class UserProgress(models.Model):
    line_user_id = models.CharField(max_length=255)
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE)
    current_course = models.ForeignKey(Course, on_delete=models.CASCADE)
    last_completed_order = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('line_user_id', 'current_course')

    class Meta:
        verbose_name = "住民のアクション履歴（学習進捗）"
        verbose_name_plural = "住民のアクション履歴（学習進捗）"

class MessageLog(models.Model):
    member = models.ForeignKey('members.AiMember', on_delete=models.CASCADE)
    role = models.CharField(max_length=10)
    text = models.TextField()
    is_escalated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "送信メッセージ履歴"
        verbose_name_plural = "送信メッセージ履歴"    

class GarbageCalendar(models.Model):
    municipality = models.CharField(max_length=50, verbose_name="市町村")
    district = models.CharField(max_length=50, verbose_name="地区")
    collection_date = models.DateField(verbose_name="収集日")
    garbage_type = models.CharField(max_length=100, verbose_name="ゴミ種別")
    notes = models.TextField(blank=True, null=True, verbose_name="注意事項等")
    other = models.TextField(blank=True, null=True, verbose_name="その他")

    class Meta:
        verbose_name = "ゴミ収集カレンダー"
        verbose_name_plural = "ゴミ収集カレンダー"
        # 同じ地区の同じ日に、同じゴミ種別が「重複登録」されるのを防ぐ
        unique_together = ('municipality', 'district', 'collection_date', 'garbage_type')
        ordering = ['collection_date']

    def __str__(self):
        return f"【{self.municipality} {self.district}】{self.collection_date.strftime('%Y/%m/%d')} : {self.garbage_type}"
    
# ==========================================
# 防災・アンケート配信機能のデータベース
# ==========================================

def get_safe_filename(instance, filename):
    """日本語ファイル名によるLINEのURL途切れを防ぐため、ランダムな英数字に自動変換する"""
    ext = filename.split('.')[-1] # 拡張子（.pdfなど）を取り出す
    new_filename = f"{uuid.uuid4().hex}.{ext}" # ランダムな英数字.pdf を作る
    return os.path.join('emergency_files/', new_filename)

class EmergencyEvent(models.Model):
    """団体が送信する「防災・アンケート配信」の箱（親）"""
    # どの自治会の配信かを厳密に紐付ける（テナント分離の要）
    politician = models.ForeignKey('bot.Politician', on_delete=models.CASCADE, verbose_name="所属団体")
    
    title = models.CharField("配信タイトル（管理用）", max_length=100)
    message_body = models.TextField("配信メッセージ本文", help_text="LINEで一斉送信されるメインの文章です。")

    # ==========================================
    # ▼ ここからセグメント配信（絞り込み）用の箱を追加
    # ==========================================
    target_group_1 = models.CharField("絞り込み: グループ1", max_length=50, blank=True, null=True)
    target_group_2 = models.CharField("絞り込み: グループ2", max_length=50, blank=True, null=True)
    target_group_3 = models.CharField("絞り込み: グループ3", max_length=50, blank=True, null=True)
    target_note_1 = models.CharField("絞り込み: 備考1", max_length=50, blank=True, null=True)
    target_note_2 = models.CharField("絞り込み: 備考2", max_length=50, blank=True, null=True)
    target_note_3 = models.CharField("絞り込み: 備考3", max_length=50, blank=True, null=True)

    attached_file = models.FileField(
        "添付ファイル (PDF等)", 
        upload_to=get_safe_filename, # ★ここを 'emergency_files/' から書き換え！
        blank=True, 
        null=True, 
        help_text="回覧板や詳細資料のPDFを添付できます（※選択するとLINEにURLが自動送信されます）。"
    )

    target_past_event = models.ForeignKey(
        'self', on_delete=models.SET_NULL, blank=True, null=True, 
        verbose_name="絞り込み対象の過去配信", 
        help_text="特定のアンケートに回答した人にのみ送る場合に選択してください。"
    )
    
    target_past_answer = models.CharField(
        "絞り込み対象の回答", max_length=50, blank=True, null=True, 
        help_text="例：「参加する」など（※過去配信を選択した場合のみ有効です）"
    )
    
    # LINEの画面上に表示させるタップ用ボタンのテキスト（最大3つ）
    choice_1 = models.CharField("選択肢1", max_length=50, default="無事です / 参加する")
    choice_2 = models.CharField("選択肢2", max_length=50, default="助けが必要 / 不参加", blank=True, null=True)
    choice_3 = models.CharField("選択肢3", max_length=50, blank=True, null=True)

    is_active = models.BooleanField("受付中", default=True, help_text="チェックを外すと回答を締め切ります")
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        verbose_name = "防災・アンケート配信"
        verbose_name_plural = "防災・アンケート配信一覧"

    def __str__(self):
        # 管理画面での表示名（そのままself.politicianを呼べば、自動的に正しい自治会名が入ります）
        return f"[{self.politician}] {self.title}"

class EmergencyResponse(models.Model):
    """住民がLINEのボタンを押した結果を記録する箱（子）"""
    event = models.ForeignKey(EmergencyEvent, on_delete=models.CASCADE, related_name='responses', verbose_name="対象イベント")
    
    # 誰が答えたか（循環参照エラーを防ぐため 'members.AiMember' と文字列で指定します）
    ai_member = models.ForeignKey('members.AiMember', on_delete=models.CASCADE, verbose_name="回答者（LINEアカウント）")
    
    answer = models.CharField("回答内容", max_length=50)
    replied_at = models.DateTimeField("回答日時", auto_now=True) # auto_now=True により、回答を変更した際に時間が更新される

    class Meta:
        verbose_name = "住民からの回答"
        verbose_name_plural = "住民からの回答一覧"
        # 1つのイベントにつき、1人の住民が複数回バラバラに回答を作らないようにする防衛策
        unique_together = ('event', 'ai_member')

    def __str__(self):
        return f"{self.ai_member.line_display_name} -> {self.answer}"

# ==========================================
# ▼ ここから「自治体管理者」用の拡張プロフィールを追加
# ==========================================
class CityAdminProfile(models.Model):
    """
    市役所の防災担当者などのアカウントに付与するプロフィール。
    このコードと一致する Politician（自治会）だけを横断管理できるようにする。
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="自治体管理者（システムユーザー）")
    city_code = models.CharField("管轄する市町村コード", max_length=20, help_text="例：45201（宮崎市）")
    city_name = models.CharField("自治体名", max_length=50, help_text="例：宮崎市")

    def __str__(self):
        return f"{self.city_name} 防災担当 ({self.user.username})"
    
    class Meta:
        verbose_name = "市町村アカウント（担当者）"
        verbose_name_plural = "市町村アカウント（担当者）"

# ==========================================
# ▼ 第2フェーズ：自治体管理者用の「横断」一斉配信モデル
# ==========================================
class CityEmergencyEvent(models.Model):
    """自治体（市役所）が、管轄する複数の自治会へ一気に一斉送信するための専用イベント"""
    city_admin = models.ForeignKey(CityAdminProfile, on_delete=models.CASCADE, verbose_name="作成者（市町村担当者）")
    title = models.CharField("タイトル（件名）", max_length=100)
    message_body = models.TextField("メッセージ本文")
    
    target_district_code = models.CharField(
        "絞り込み対象の町・字コード", max_length=50, blank=True, null=True,
        help_text="特定の地区のみに送る場合に入力（例：yoshimura）。空欄なら管轄内すべての自治会へ一斉送信されます。"
    )

    # ▼▼▼ 今回新しく追加する「行政独自のタグ絞り込み」 ▼▼▼
    target_group_1 = models.CharField("絞り込み: グループ1", max_length=50, blank=True, null=True)
    target_group_2 = models.CharField("絞り込み: グループ2", max_length=50, blank=True, null=True)
    target_group_3 = models.CharField("絞り込み: グループ3", max_length=50, blank=True, null=True)
    target_note_1 = models.CharField("絞り込み: 備考1", max_length=100, blank=True, null=True)
    target_note_2 = models.CharField("絞り込み: 備考2", max_length=100, blank=True, null=True)
    target_note_3 = models.CharField("絞り込み: 備考3", max_length=100, blank=True, null=True)
    # ▲▲▲ 追加ここまで ▲▲▲
    
    attached_file = models.FileField(
        "添付ファイル (PDF等)", upload_to=get_safe_filename, blank=True, null=True,
        help_text="避難所の地図などのPDFを添付できます。"
    )

    choice_1 = models.CharField("選択肢1", max_length=20, blank=True, null=True, help_text="例: 無事です")
    choice_2 = models.CharField("選択肢2", max_length=20, blank=True, null=True, help_text="例: 支援が必要")
    choice_3 = models.CharField("選択肢3", max_length=20, blank=True, null=True)
    
    is_active = models.BooleanField("受付中（有効）", default=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    def __str__(self):
        return f"【市町村横断】{self.title} ({self.city_admin.city_name})"
    
    class Meta:
        verbose_name = "市町村・横断一斉送信（イベント）"
        verbose_name_plural = "市町村・横断一斉送信（イベント）"

# ==========================================
# ▼ 新しく追加する「行政用の回答集計箱」
# ==========================================
class CityEmergencyResponse(models.Model):
    """住民が行政からの横断メッセージのボタンをタップした結果を記録する箱"""
    event = models.ForeignKey(CityEmergencyEvent, on_delete=models.CASCADE, verbose_name="対象の市町村配信")
    ai_member = models.ForeignKey('members.AiMember', on_delete=models.CASCADE, verbose_name="回答者")
    answer = models.CharField("回答内容", max_length=50)
    replied_at = models.DateTimeField("回答日時", auto_now_add=True)

    class Meta:
        verbose_name = "市町村配信への回答"
        verbose_name_plural = "市町村配信への回答"
        unique_together = ('event', 'ai_member') # 1回の配信につき、1人1回だけ回答できるようにする防衛策

    def __str__(self):
        return f"{self.ai_member} -> {self.answer}"
    
# ==========================================
# ▼ 新しく追加する「行政専用の住民タグ箱」
# ==========================================
class CityMemberProfile(models.Model):
    """市役所が各住民に対して独自にタグ付け（グループ・備考）するための専用データベース"""
    city_admin = models.ForeignKey(CityAdminProfile, on_delete=models.CASCADE, verbose_name="管轄市町村")
    ai_member = models.ForeignKey('members.AiMember', on_delete=models.CASCADE, verbose_name="対象住民")
    
    group_1 = models.CharField("グループ1", max_length=50, blank=True, null=True)
    group_2 = models.CharField("グループ2", max_length=50, blank=True, null=True)
    group_3 = models.CharField("グループ3", max_length=50, blank=True, null=True)
    
    note_1 = models.CharField("備考1", max_length=100, blank=True, null=True)
    note_2 = models.CharField("備考2", max_length=100, blank=True, null=True)
    note_3 = models.CharField("備考3", max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = "市町村・住民プロフィール（独自タグ）"
        verbose_name_plural = "市町村・住民プロフィール（独自タグ）"
        unique_together = ('city_admin', 'ai_member') # 重複してタグ付けされるのを防ぐ防衛策

    def __str__(self):
        return f"{self.ai_member.real_name or '名無し'} の行政プロファイル ({self.city_admin.city_name})"

def public_page_image_path(instance, filename):
    """
    S3への自動ルーティング関数（CMS用）
    保存先例: tenant_1/site_assets/top_image.jpg
    """
    p_id = getattr(instance.politician, 'id', 'unknown')
    return f'tenant_{p_id}/site_assets/{filename}'

class PublicPageConfig(models.Model):
    """各自治会の公開ホームページ（CMS）の設定を保持するモデル"""
    
    # 運営側の防衛的視点: OneToOneFieldにより「1つの自治会につき1つの設定」を強制し、データ重複エラーを防ぐ
    politician = models.OneToOneField(
        'bot.Politician', 
        on_delete=models.CASCADE, 
        related_name='page_config', 
        verbose_name="対象自治会"
    )
    
    # --- デザイン設定 ---
    main_visual = models.ImageField(
        "トップ画像", 
        upload_to=public_page_image_path, 
        blank=True, 
        null=True, 
        help_text="※スマホ画面の上部に表示される看板画像です（10MB以下の横長画像を推奨）"
    )
    accent_color = models.CharField(
        "アクセントカラー", 
        max_length=7, 
        default="#2c3e50", 
        help_text="例: #2c3e50（ヘッダー等の色を指定する16進数コード）"
    )
    
    # --- コンテンツ設定 ---
    welcome_text = models.TextField(
        "あいさつ文", 
        default="私たちの自治会へようこそ。", 
        help_text="トップページに表示されるメッセージです。"
    )
    show_announcements = models.BooleanField("お知らせ一覧を表示する", default=True)
    show_events = models.BooleanField("行事カレンダーを表示する", default=True)
    show_library = models.BooleanField("公開資料室を表示する", default=True)
    
    # --- 公開制御 ---
    is_public = models.BooleanField(
        "ページを公開する", 
        default=False, 
        help_text="※チェックを入れると、外部からURLでアクセス可能になります。準備中は外してください。"
    )
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "公開ページ（CMS）設定"
        verbose_name_plural = "公開ページ（CMS）設定一覧"

    def __str__(self):
        return f"{self.politician.name} のページ設定"
    
    # ▼▼▼ 新規追加: 医療圏の複数選択フィールド ▼▼▼
    target_medical_areas = models.ManyToManyField(
        'events.MedicalArea', 
        blank=True, 
        verbose_name="表示対象の医療圏",
        help_text="この地域にお住まいの住民へ表示する当番医のエリアを選択してください。"
    )
    
    target_condolence_areas = models.ManyToManyField(
        'Municipality', # ←上で定義した市町村マスタクラス名
        blank=True, 
        verbose_name="おくやみ情報の表示エリア",
        help_text="この自治会ページに表示するおくやみ情報の市町村を選択してください。（例：宮崎市と近隣市町村を選択）"
    )       

class BroadcastMessage(models.Model):
    """LINE一斉送信メッセージ（誤送信防止・履歴管理用）"""
    politician = models.ForeignKey(
        'Politician', on_delete=models.CASCADE, related_name='broadcasts', verbose_name='対象自治会'
    )
    title = models.CharField("管理用タイトル（住民には見えません）", max_length=100, help_text="例：令和6年度 総会のお知らせ配信")
    message_text = models.TextField("LINE送信テキスト", help_text="※実際に住民のLINEに届く文章です。URL等もここに含めてください。")
    
    # 🛡️ 運営側の防衛的視点: 即時送信させず、必ず「下書き」として保存させる
    is_sent = models.BooleanField("送信済", default=False)
    sent_at = models.DateTimeField("送信日時", null=True, blank=True)
    target_count = models.IntegerField("送信成功人数", default=0, help_text="送信完了時にシステムが自動記録します")
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        verbose_name = "LINE一斉送信メッセージ"
        verbose_name_plural = "LINE一斉送信履歴"
        ordering = ['-created_at']

    def __str__(self):
        status = "✅ 送信済" if self.is_sent else "📝 未送信（下書き）"
        return f"[{status}] {self.title}"

 # ==========================================
# 1. 市町村マスタ（新規追加：将来の県全域・全国展開用）
# ==========================================
class Municipality(models.Model):
    prefecture = models.CharField("都道府県", max_length=10, default="宮崎県")
    name = models.CharField("市町村名", max_length=50, help_text="例：宮崎市、都城市")

    class Meta:
        verbose_name = "市町村"
        verbose_name_plural = "市町村マスタ"
        ordering = ['prefecture', 'name']

    def __str__(self):
        return f"{self.prefecture} {self.name}"

# ==========================================
# 2. 葬祭場マスタ（市町村マスタと紐付け）
# ==========================================
class FuneralHall(models.Model):
    name = models.CharField("葬祭場名", max_length=100)
    # 🛡️ 拡張性: 葬儀場が「どの市町村にあるか」を持たせる
    municipality = models.ForeignKey(Municipality, on_delete=models.PROTECT, verbose_name="所在市町村", null=True)
    address = models.CharField("所在地", max_length=200)
    phone = models.CharField("電話番号", max_length=20, blank=True)
    latitude = models.DecimalField("緯度", max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField("経度", max_digits=9, decimal_places=6, blank=True, null=True)

    class Meta:
        verbose_name = "葬祭場"
        verbose_name_plural = "葬祭場マスタ"
        ordering = ['municipality', 'name']

    def __str__(self):
        return self.name

# ==========================================
# 3. おくやみ情報（テナント依存から独立した純粋なトランザクション）
# ==========================================
class Condolence(models.Model):
    CEREMONY_CHOICES = [
        ('仏式', '仏式'),
        ('神式', '神式'),
        ('キリスト教式', 'キリスト教式'),
        ('無宗教', '無宗教'),
        ('未定・その他', '未定・その他'),
    ]

    # 故人の情報
    deceased_name = models.CharField("故人氏名", max_length=100)
    age = models.PositiveIntegerField("年齢", null=True, blank=True)
    deceased_address = models.CharField("住所", max_length=100)
    
    # 葬儀情報
    wake_datetime = models.DateTimeField("通夜 日時", null=True, blank=True)
    funeral_datetime = models.DateTimeField("告別式 日時", null=True, blank=True)
    ceremony_type = models.CharField("葬儀種別", max_length=20, choices=CEREMONY_CHOICES, default='仏式')
    
    # 葬祭場
    funeral_hall = models.ForeignKey(FuneralHall, on_delete=models.PROTECT, verbose_name="葬祭場", null=True, blank=True)

    class Meta:
        verbose_name = "おくやみ情報"
        verbose_name_plural = "おくやみ情報一覧"

    def __str__(self):
        return f"{self.deceased_name} 様 ({self.funeral_datetime.strftime('%Y/%m/%d') if self.funeral_datetime else '日程未定'})"
