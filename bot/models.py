from django.db import models
from django.contrib.auth.models import User
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

class UserProgress(models.Model):
    line_user_id = models.CharField(max_length=255)
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE)
    current_course = models.ForeignKey(Course, on_delete=models.CASCADE)
    last_completed_order = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('line_user_id', 'current_course')

class MessageLog(models.Model):
    member = models.ForeignKey('members.AiMember', on_delete=models.CASCADE)
    role = models.CharField(max_length=10)
    text = models.TextField()
    is_escalated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

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
    
    # 添付ファイル機能（デジタル回覧板）も行政が使えるように標準装備
    attached_file = models.FileField(
        "添付ファイル (PDF等)", upload_to=get_safe_filename, blank=True, null=True,
        help_text="避難所の地図などのPDFを添付できます。"
    )
    
    is_active = models.BooleanField("受付中（有効）", default=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    def __str__(self):
        return f"【市町村横断】{self.title} ({self.city_admin.city_name})"
        