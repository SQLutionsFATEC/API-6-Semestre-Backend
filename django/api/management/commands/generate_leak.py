from django.core.management.base import BaseCommand
from api.db_routers import VAZAMENTO_DB
from api.models import Vazamento
from api.services.aviso_vazamento import enviar_aviso_vazamento
from api.views.vazamento_api import _sinalizar_restauracao_backup

class Command(BaseCommand):
    help = (
        'Gera um novo incidente de vazamento de dados, aciona a restauração de '
        'backup e avisa por e-mail os usuários afetados'
    )

    def handle(self, *args, **kwargs):
        vazamento = Vazamento.objects.using(VAZAMENTO_DB).create()
        self.stdout.write(self.style.SUCCESS(f'Incidente registrado com sucesso! ID: {vazamento.id}'))

        _sinalizar_restauracao_backup()
        self.stdout.write(self.style.SUCCESS('Sinal de restauração enviado. O watcher.sh no host irá processar.'))

        # Best-effort, depois do registro e da sinalização: uma falha no envio
        # não desfaz nenhum dos dois passos nem falha o comando.
        enviados = enviar_aviso_vazamento(vazamento)
        self.stdout.write(self.style.SUCCESS(
            f'Aviso de vazamento enviado para {enviados} destinatário(s).'
        ))
