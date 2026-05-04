from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum
from .models import FiscalYear, Transaction
from events.models import Event # 他アプリ(events)から行事データを引っ張る

# 🛡️ 運営側の防衛的視点: 役員（管理者）以外がアクセスできないよう強制ブロック
@staff_member_required
def assembly_report_view(request, year_id):
    """総会資料（事業報告・決算報告）の自動生成ビュー"""
    
    fiscal_year = get_object_or_404(FiscalYear, id=year_id)
    politician = fiscal_year.politician

    # 1. 事業報告（該当年度のイベントを自動抽出）
    activities = Event.objects.filter(
        politician=politician,
        start_time__date__gte=fiscal_year.start_date,
        start_time__date__lte=fiscal_year.end_date
    ).order_by('start_time')

    # 2. 収支決算報告（取消済の伝票を計算から完全に除外した安全なデータ）
    valid_transactions = Transaction.objects.filter(
        fiscal_year=fiscal_year,
        is_cancelled=False
    )

    # 収入科目の自動集計
    incomes = valid_transactions.filter(category__category_type='INCOME') \
        .values('category__name') \
        .annotate(total=Sum('amount')) \
        .order_by('category__order')

    # 支出科目の自動集計
    expenses = valid_transactions.filter(category__category_type='EXPENSE') \
        .values('category__name') \
        .annotate(total=Sum('amount')) \
        .order_by('category__order')

    total_income = sum(item['total'] for item in incomes) if incomes else 0
    total_expense = sum(item['total'] for item in expenses) if expenses else 0
    carry_over_balance = total_income - total_expense

    # ==========================================
    # ▼▼▼ 新規追加：3. 次年度予算案の自動取得と計算 ▼▼▼
    # ==========================================
    # 🛡️ 現在の年度の終了日より後に始まる「次年度」のデータを自動検索
    next_year = FiscalYear.objects.filter(
        politician=politician,
        start_date__gt=fiscal_year.end_date
    ).order_by('start_date').first()

    budget_incomes = []
    budget_expenses = []
    next_total_income = carry_over_balance  # 🎯 実務直結機能: 当年度の繰越金を、次年度収入のベース額（初期値）として自動セット
    next_total_expense = 0

    if next_year:
        # 次年度に紐づく予算データを取得
        all_budgets = next_year.budgets.select_related('category').all()
        
        budget_incomes = [b for b in all_budgets if b.category.category_type == 'INCOME']
        budget_expenses = [b for b in all_budgets if b.category.category_type == 'EXPENSE']
        
        next_total_income += sum(b.amount for b in budget_incomes)
        next_total_expense += sum(b.amount for b in budget_expenses)

    # ==========================================


    context = {
        'fiscal_year': fiscal_year,
        'activities': activities,
        'incomes': incomes,
        'expenses': expenses,
        'total_income': total_income,
        'total_expense': total_expense,
        'carry_over_balance': carry_over_balance,
        'next_year': next_year,
        'budget_incomes': budget_incomes,
        'budget_expenses': budget_expenses,
        'next_total_income': next_total_income,
        'next_total_expense': next_total_expense,        
    }
    return render(request, 'accounting/assembly_report.html', context)
