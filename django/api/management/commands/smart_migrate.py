from django.core.management.base import BaseCommand, CommandError # <-- Adicionado CommandError
from django.core.management import call_command
from django.db import connection
import os
from django.conf import settings

class Command(BaseCommand):
    help = 'Executa migrações de forma inteligente: do zero se o banco estiver vazio, ou normal caso contrário.'

    def handle(self, *args, **kwargs):
        try: # <-- Iniciamos um bloco Try para capturar absolutamente qualquer erro
            tables = connection.introspection.table_names()

            is_empty = len(tables) == 0 or tables == ['django_migrations']

            if is_empty:
                self.stdout.write(
                    self.style.WARNING(
                        "Banco de dados vazio detectado. Executando migração única 'from scratch'..."
                    )
                )

                # A migração "from scratch" está em um arquivo de migração do Django na pasta api/from_scratch.
                sql_dir = os.path.join(settings.BASE_DIR, 'api', 'from_scratch')
                init_file = os.path.join(sql_dir, '__init__.py')

                if os.path.exists(sql_dir):
                    if not os.path.exists(init_file):
                        with open(init_file, 'w') as _:
                            pass

                    self.stdout.write(
                        "Configurando o Django para usar a migração 'from scratch'..."
                    )

                    if (
                        not hasattr(settings, 'MIGRATION_MODULES')
                        or settings.MIGRATION_MODULES is None
                    ):
                        settings.MIGRATION_MODULES = {}
                    settings.MIGRATION_MODULES['api'] = 'api.from_scratch'

                    self.stdout.write("Aplicando migrações no banco de dados...")
                    call_command('migrate')

                    settings.MIGRATION_MODULES.pop('api')

                    self.stdout.write(
                        "Marcando o restante das migrações regulares do app 'api' como concluídas (fake)..."
                    )
                    call_command('migrate', 'api', fake=True)

                    self.stdout.write(
                        self.style.SUCCESS("Migração 'from scratch' concluída com sucesso!")
                    )
                else:
                    # Correção: Levantar CommandError ao invés de apenas imprimir em vermelho.
                    # Isso força a parada imediata e devolve Exit Code 1 para o Docker/bash.
                    raise CommandError(
                        f"Diretório não encontrado: {sql_dir}. Crie o diretório com a sua Migration inicial."
                    )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        "Banco de dados já contém tabelas. Executando migração normal..."
                    )
                )
                call_command('migrate')
                self.stdout.write(
                    self.style.SUCCESS("Migração normal concluída com sucesso!")
                )

        except Exception as e:
            # Se QUALQUER coisa der errado (falha no banco, timeout, diretório faltando),
            # o CommandError grita o erro e derruba o processo com Exit Code 1.
            raise CommandError(f"Erro crítico durante o smart_migrate: {str(e)}")