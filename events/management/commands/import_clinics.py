import csv
from django.core.management.base import BaseCommand
from events.models import MedicalInstitution

class Command(BaseCommand):
    help = '医療機関マスタをCSVから一括インポートします'

    def add_arguments(self, parser):
        # コマンド実行時にCSVファイルのパスを受け取る設定
        parser.add_argument('csv_path', type=str, help='インポートするCSVファイルのパス')

    def handle(self, *args, **kwargs):
        csv_path = kwargs['csv_path']
        
        try:
            # 🛡️ 運営側の防衛的視点1: 'utf-8-sig' でWindowsエクセルのBOM（文字化け原因）を吸収
            with open(csv_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                success_count = 0
                update_count = 0

                for row in reader:
                    name = row.get('病院名')
                    if not name:
                        continue  # 空行はスキップ

                    # 🛡️ 運営側の防衛的視点2: update_or_create による二重登録の完全ブロック
                    # 病院名が一致するデータがあれば「上書き更新」、なければ「新規作成」を行う
                    obj, created = MedicalInstitution.objects.update_or_create(
                        name=name.strip(),
                        defaults={
                            'address': row.get('住所', '').strip(),
                            'phone': row.get('電話番号', '').strip(),
                            'is_active': True
                        }
                    )
                    
                    if created:
                        success_count += 1
                    else:
                        update_count += 1

            self.stdout.write(self.style.SUCCESS(
                f'完了: {success_count}件を新規登録、{update_count}件を更新しました。'
            ))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'エラー: ファイル {csv_path} が見つかりません。'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'予期せぬエラーが発生しました: {str(e)}'))