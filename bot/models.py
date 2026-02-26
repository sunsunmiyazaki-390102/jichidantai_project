from django.db import models

class Politician(models.Model):
    name = models.CharField("自治会名", max_length=100)
    slug = models.SlugField("スラグ（URL用）", unique=True)
    line_channel_secret = models.CharField(max_length=255)
    line_access_token = models.TextField()
    openai_api_key = models.CharField(max_length=255, blank=True, null=True)
    openai_assistant_id = models.CharField(max_length=255, blank=True, null=True)
    ai_model_name = models.CharField(max_length=50, default="gpt-4o")
    system_prompt = models.TextField(blank=True, null=True)
    
    # ゴミ収集地区グループ
    GOMI_REGION_CHOICES = [
        ('miyazaki_kita_a', '宮崎市：北A地区'),
        ('miyazaki_kita_b', '宮崎市：北B地区'),
        ('miyazaki_minami_a', '宮崎市：南A地区'),
        ('miyazaki_minami_b', '宮崎市：南B地区'),
    ]
    gomi_region = models.CharField("ゴミ収集地区グループ", max_length=50, choices=GOMI_REGION_CHOICES, blank=True, null=True)

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