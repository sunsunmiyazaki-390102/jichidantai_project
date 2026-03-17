from django.apps import AppConfig

class BotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bot'
    # ▼▼▼ 新規追加：管理画面での表示名を綺麗な日本語にする ▼▼▼
    verbose_name = '2. 配信・イベント・防災メニュー'
    