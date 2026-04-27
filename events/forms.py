from django import forms
from .models import SurveyResponse

class SurveyResponseForm(forms.ModelForm):
    class Meta:
        model = SurveyResponse
        fields = ['respondent_name', 'attendance', 'comment']
        widgets = {
            'respondent_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '例：1区 坂井 康夫',
            }),
            'attendance': forms.RadioSelect(attrs={'class': 'form-check-input'}),
            'comment': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'ご意見等があれば入力してください',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 高齢者への配慮: 必須項目を明示
        self.fields['respondent_name'].required = True
        self.fields['attendance'].required = True