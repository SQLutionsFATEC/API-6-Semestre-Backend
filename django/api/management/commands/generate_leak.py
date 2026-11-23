from django.core.management.base import BaseCommand
from api.models import Vazamento
from api.views.vazamento_api import _sinalizar_restauracao_backup

class Command(BaseCommand):
    help = 'Gera um novo incidente de vazamento de dados e aciona a restauração de backup'

    def handle(self, *args, **kwargs):
        vazamento = Vazamento.objects.create()
        self.stdout.write(self.style.SUCCESS(f'Incidente registrado com sucesso! ID: {vazamento.id}'))

        _sinalizar_restauracao_backup()
        self.stdout.write(self.style.SUCCESS('Sinal de restauração enviado. O watcher.sh no host irá processar.'))