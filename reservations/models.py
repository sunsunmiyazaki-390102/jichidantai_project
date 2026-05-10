from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from bot.models import Politician

class Facility(models.Model):
    """貸出施設（公民館、会議室等）"""
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="対象自治会")
    name = models.CharField("施設名", max_length=100)
    description = models.TextField("説明", blank=True)
    capacity = models.PositiveIntegerField("収容人数", default=0)
    is_active = models.BooleanField("予約受付中", default=True)

    class Meta:
        verbose_name = "1. 貸出施設マスタ"
        verbose_name_plural = "1. 貸出施設マスタ"

    def __str__(self):
        return f"{self.name} ({self.politician.name})"

class Reservation(models.Model):
    """予約データ"""
    STATUS_CHOICES = [
        ('PENDING', '承認待ち'),
        ('APPROVED', '承認済'),
        ('REJECTED', '却下'),
        ('CANCELLED', 'キャンセル'),
    ]
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, verbose_name="施設", related_name="reservations")
    user_name = models.CharField("予約者・団体名", max_length=100)
    user_phone = models.CharField("連絡先電話番号", max_length=20, blank=True)
    date = models.DateField("利用日")
    start_time = models.TimeField("開始時間")
    end_time = models.TimeField("終了時間")
    purpose = models.CharField("利用目的", max_length=200)
    status = models.CharField("予約状況", max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    applicant_line_id = models.CharField('申請者のLINE User ID', max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "2. 予約一覧"
        verbose_name_plural = "2. 予約一覧"
        ordering = ['date', 'start_time']

    def __str__(self):
        return f"{self.date} {self.start_time}-{self.end_time} : {self.user_name}"

    # 🛡️ 運営側の防衛的視点: 重複予約をシステムレベルで遮断する
    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError("終了時間は開始時間より後の時刻を指定してください。")

        # 過去の日付への予約を制限
        if self.date < timezone.localtime().date():
             raise ValidationError("過去の日付で予約することはできません。")

        # 同一施設・同一日の既存予約（承認済または承認待ち）との重複チェック
        overlapping = Reservation.objects.filter(
            facility=self.facility,
            date=self.date,
            status__in=['PENDING', 'APPROVED']
        ).exclude(id=self.id)

        for res in overlapping:
            if (self.start_time < res.end_time and self.end_time > res.start_time):
                raise ValidationError(
                    f"⚠️ 時間が重複しています: {res.start_time.strftime('%H:%M')}〜{res.end_time.strftime('%H:%M')} に「{res.user_name}」様の予約があります。"
                )
            