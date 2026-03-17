from django.apps import AppConfig

class MembersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'members'
    # ▼▼▼ 新規追加：管理画面での表示名を綺麗な日本語にする ▼▼▼
    verbose_name = '1. 名簿・住民管理'
    