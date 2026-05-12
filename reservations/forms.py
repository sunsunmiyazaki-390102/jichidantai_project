from django import forms
from .models import Reservation, Facility
from django.core.exceptions import ValidationError

class ReservationForm(forms.ModelForm):
    class Meta:
        model = Reservation
        fields = ['facility', 'user_name', 'user_phone', 'date', 'start_time', 'end_time', 'purpose']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'purpose': forms.Textarea(attrs={'rows': 2, 'placeholder': '例：子ども会役員会'}),
        }

    def __init__(self, *args, **kwargs):
        # 🛡️ 運営側の防衛的視点: ビューから渡された現在のテナント（自治会）情報を抽出
        # kwargsから 'politician' を取り出し、親クラスの初期化前に除外する
        politician = kwargs.pop('politician', None)
        
        super().__init__(*args, **kwargs)
        
        # 抽出したテナント情報を使って、施設の選択肢（queryset）を物理的に制限する
        if politician:
            self.fields['facility'].queryset = Facility.objects.filter(
                politician=politician, 
                is_active=True
            )

    def clean(self):
        cleaned_data = super().clean()
        facility = cleaned_data.get('facility')
        date = cleaned_data.get('date')
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        if not all([facility, date, start_time, end_time]):
            return cleaned_data

        # 🛡️ 運営側の防衛的視点: 重複予約の厳格な検証
        # 承認済(APPROVED)または承認待ち(PENDING)の予約と時間が重なっていないか確認
        overlapping = Reservation.objects.filter(
            facility=facility,
            date=date,
            status__in=['PENDING', 'APPROVED']
        )
        
        # 既存の予約時間 (A_start < B_end AND A_end > B_start) の数式で重複を判定
        for res in overlapping:
            if start_time < res.end_time and end_time > res.start_time:
                raise ValidationError(
                    f"申し訳ありません。{res.start_time.strftime('%H:%M')}〜{res.end_time.strftime('%H:%M')} は既に予約が入っています。"
                )
        return cleaned_data
    