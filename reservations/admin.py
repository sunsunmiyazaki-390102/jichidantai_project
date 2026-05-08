from django.contrib import admin
from .models import Facility, Reservation

@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'politician', 'capacity', 'is_active')
    list_filter = ('politician', 'is_active')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('date', 'facility', 'start_time', 'end_time', 'user_name', 'status')
    list_filter = ('status', 'date', 'facility')
    search_fields = ('user_name', 'purpose')
    date_hierarchy = 'date'
    
    # 🛡️ 運営側の防衛的視点: 承認作業を効率化するためのアクション
    actions = ['approve_reservations', 'reject_reservations']

    @admin.action(description='選択した予約を「承認済」にする')
    def approve_reservations(self, request, queryset):
        queryset.update(status='APPROVED')
        self.message_user(request, f"{queryset.count()}件の予約を承認しました。")

    @admin.action(description='選択した予約を「却下」にする')
    def reject_reservations(self, request, queryset):
        queryset.update(status='REJECTED')
        self.message_user(request, f"{queryset.count()}件の予約を却下しました。")
        