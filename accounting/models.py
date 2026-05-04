from django.db import models
from django.core.exceptions import ValidationError
from bot.models import Politician  # 自治会（テナント）マスタをインポート

# ==========================================
# 1. 会計年度マスタ（過去データのロック制御）
# ==========================================
class FiscalYear(models.Model):
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="対象自治会")
    name = models.CharField("年度名", max_length=50, help_text="例：令和8年度")
    start_date = models.DateField("開始日")
    end_date = models.DateField("終了日")
    # 🛡️ 防衛的視点: 監査が終わった過去の年度を「書き換え不可」にする絶対的なロックキー
    is_locked = models.BooleanField("会計ロック（締結済）", default=False, help_text="チェックを入れると、この年度の伝票は一切追加・修正できなくなります。")

    class Meta:
        verbose_name = "会計年度"
        verbose_name_plural = "1. 会計年度マスタ"
        ordering = ['-start_date']
        unique_together = ('politician', 'name')

    def __str__(self):
        lock_mark = "🔒 " if self.is_locked else "🔓 "
        return f"{lock_mark}{self.name} ({self.politician.name})"

# ==========================================
# 2. 勘定科目マスタ（テナント独立の拡張性）
# ==========================================
class AccountCategory(models.Model):
    TYPE_CHOICES = [
        ('INCOME', '収入'),
        ('EXPENSE', '支出'),
    ]
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="対象自治会")
    name = models.CharField("科目名", max_length=50, help_text="例：自治会費、防犯灯電気代など")
    category_type = models.CharField("収支区分", max_length=10, choices=TYPE_CHOICES)
    order = models.PositiveIntegerField("並び順", default=0)
    is_active = models.BooleanField("有効", default=True)

    class Meta:
        verbose_name = "勘定科目"
        verbose_name_plural = "2. 勘定科目マスタ"
        ordering = ['category_type', 'order']

    def __str__(self):
        return f"[{self.get_category_type_display()}] {self.name}"

# ==========================================
# 3. 出納伝票（トランザクション：完全追記型アーキテクチャ）
# ==========================================
class Transaction(models.Model):
    politician = models.ForeignKey(Politician, on_delete=models.CASCADE, verbose_name="対象自治会")
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, verbose_name="会計年度")
    date = models.DateField("取引日")
    category = models.ForeignKey(AccountCategory, on_delete=models.PROTECT, verbose_name="勘定科目")
    
    amount = models.IntegerField("金額")
    description = models.CharField("摘要（詳細）", max_length=200)
    receipt_image = models.ImageField("領収書画像", upload_to='receipts/%Y/%m/', blank=True, null=True)

    # 🛡️ 究極の防衛的視点: 取消伝票（赤黒処理）
    is_cancelled = models.BooleanField("取消済", default=False)
    cancelled_reason = models.CharField("取消理由", max_length=100, blank=True)

    class Meta:
        verbose_name = "出納伝票"
        verbose_name_plural = "3. 出納帳（伝票一覧）"
        ordering = ['-date', '-id']

    def __str__(self):
        status = "【取消済】 " if self.is_cancelled else ""
        return f"{status}{self.date} - {self.category.name}: ¥{self.amount:,}"

    def clean(self):
        super().clean()
        if self.fiscal_year and self.fiscal_year.is_locked:
            raise ValidationError("この会計年度は既にロック（締結済）されているため、伝票の操作はできません。")
        if self.amount is not None and self.amount < 0:
            raise ValidationError("金額は0以上で入力してください。訂正する場合は「取消」機能を使用します。")

    def delete(self, *args, **kwargs):
        raise ValidationError("【セキュリティ警告】出納伝票の物理的な削除は禁止されています。誤入力を修正する場合は「取消（赤黒処理）」を行ってください。")

# ==========================================
# 4. 予算管理（次年度予算案の作成用）
# ==========================================
class Budget(models.Model):
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, verbose_name="対象年度", related_name="budgets")
    category = models.ForeignKey(AccountCategory, on_delete=models.CASCADE, verbose_name="勘定科目")
    amount = models.IntegerField("予算額", default=0)

    class Meta:
        verbose_name = "予算"
        verbose_name_plural = "4. 予算管理マスタ"
        unique_together = ('fiscal_year', 'category')
        ordering = ['category__category_type', 'category__order']

    def __str__(self):
        return f"{self.fiscal_year.name} - {self.category.name}: ¥{self.amount:,}"
        