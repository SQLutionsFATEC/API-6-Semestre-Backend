import os
import importlib
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.test.utils import setup_databases, teardown_databases


class Command(BaseCommand):
    help = 'Executa o setUp de uma classe de teste isolada num banco de testes e exporta o resultado como fixture.'

    def add_arguments(self, parser):
        parser.add_argument(
            'test_class_path',
            type=str,
            help='Caminho para a classe de teste (ex: api.tests.test_fornecedores.FornecedoresPedidosApiTest)',
        )
        parser.add_argument(
            'fixture_name', type=str, help='Nome da fixture a ser gerada (sem .json)'
        )

    def handle(self, *args, **kwargs):
        test_class_path = kwargs['test_class_path']
        fixture_name = kwargs['fixture_name']

        if fixture_name.endswith('.json'):
            fixture_name = fixture_name[:-5]

        module_path, class_name = test_class_path.rsplit('.', 1)
        self.stdout.write(f"Importando {class_name} de {module_path}...")
        module = importlib.import_module(module_path)
        test_class = getattr(module, class_name)

        self.stdout.write("Criando banco de dados de teste...")
        old_config = setup_databases(verbosity=1, interactive=False)

        try:
            self.stdout.write("Executando o setUp() da classe...")
            # Pega o primeiro método de teste disponível só para inicializar a classe
            methods = [m for m in dir(test_class) if m.startswith('test_')]
            method_name = methods[0] if methods else '__doc__'
            instance = test_class(methodName=method_name)

            # Precisamos configurar a classe para o banco de testes
            if hasattr(instance, '_pre_setup'):
                instance._pre_setup()

            instance.setUp()

            self.stdout.write("Iniciando exportação...")
            call_command('generate_fixture', fixture_name)

            self.stdout.write(self.style.SUCCESS('✅ Comando concluído!'))

        finally:
            self.stdout.write("Destruindo banco de dados de teste...")
            teardown_databases(old_config, verbosity=1)
