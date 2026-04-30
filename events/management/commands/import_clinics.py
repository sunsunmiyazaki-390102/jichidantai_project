import csv
from django.core.management.base import BaseCommand
from events.models import MedicalInstitution, MedicalArea

class Command(BaseCommand):
    help = '医療機関マスタをCSVから一括インポートします（新アーキテクチャ対応版）'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str, help='インポートするCSVファイルのパス')

    def handle(self, *args, **kwargs):
        csv_path = kwargs['csv_path']
        
        try:
            with open(csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                success_count = 0
                update_count = 0
                error_count = 0

                for row_num, row in enumerate(reader, 1):
                    name = row.get('病院名')
                    if not name:
                        continue  # 空行はスキップ

                    # 🛡️ 防衛的視点1: 医療圏マスタの厳格な引き当て
                    area_name = row.get('医療圏', '').strip()
                    area = None
                    if area_name:
                        try:
                            area = MedicalArea.objects.get(name=area_name)
                        except MedicalArea.DoesNotExist:
                            self.stdout.write(self.style.WARNING(f"警告: 行 {row_num} の医療圏 '{area_name}' がマスタに存在しないためスキップしました。"))
                            error_count += 1
                            continue # 医療圏がない致命的なデータは弾く

                    # 🛡️ 防衛的視点2: 空白の緯度・経度を安全にパース
                    lat_str = row.get('緯度', '').strip()
                    lng_str = row.get('経度', '').strip()
                    lat = float(lat_str) if lat_str else None
                    lng = float(lng_str) if lng_str else None

                    is_active = str(row.get('有効フラグ', '1')).strip() in ['1', 'True', 'true']

                    # update_or_create による二重登録ブロック
                    obj, created = MedicalInstitution.objects.update_or_create(
                        name=name.strip(),
                        defaults={
                            'name_kana': row.get('ふりがな', '').strip(),
                            'area': area,
                            'department': row.get('診療科目', '').strip(),
                            'address': row.get('住所', '').strip(),
                            'phone': row.get('電話番号', '').strip(),
                            'website_url': row.get('公式サイトURL', '').strip(),
                            'latitude': lat,
                            'longitude': lng,
                            'is_active': is_active
                        }
                    )
                    
                    if created:
                        success_count += 1
                    else:
                        update_count += 1

            self.stdout.write(self.style.SUCCESS(
                f'完了: {success_count}件を新規登録、{update_count}件を更新、{error_count}件のエラー。'
            ))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'エラー: ファイル {csv_path} が見つかりません。'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'予期せぬエラーが発生しました: {str(e)}'))
            