import os
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = 'Gera uma nova fixture (Golden Database) a partir dos dados atuais do banco de dados.'

    def add_arguments(self, parser):
        parser.add_argument(
            'name',
            type=str,
            help='O nome da fixture que será criada (não precisa colocar .json no final)',
        )

    def handle(self, *args, **kwargs):
        name = kwargs['name']

        # Se o usuário colocar .json no nome, nós removemos para padronizar
        if name.endswith('.json'):
            name = name[:-5]

        filename = f"api/fixtures/{name}.json"

        self.stdout.write(
            f'Exportando dados do app "api" para a fixture: {filename}...'
        )

        try:
            # Garante que a pasta api/fixtures/ existe
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            # Roda o comando nativo dumpdata apenas no app api, identando com 4 espaços para legibilidade
            with open(filename, 'w', encoding='utf-8') as f:
                call_command('dumpdata', 'api', indent=4, stdout=f)

            # Ajusta permissões do arquivo gerado para pertencer ao dono do projeto (ao invés do root do docker)
            try:
                # Usa o diretório pai para pegar o UID e GID do host
                stat_info = os.stat(os.path.dirname(filename))
                os.chown(filename, stat_info.st_uid, stat_info.st_gid)
            except Exception:
                pass

            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Sucesso! Fixture "{filename}" criada e pronta para uso nos testes.'
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f'Dica: Adicione `fixtures = ["{name}.json"]` na sua classe de teste!'
                )
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Erro ao gerar a fixture: {str(e)}'))
