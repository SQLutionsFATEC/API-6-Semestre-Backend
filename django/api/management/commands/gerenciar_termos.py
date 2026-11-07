"""Comando CLI para gerenciar e versionar Termos de Consentimento e Cláusulas.

Exemplos de uso:
  # Inicializar termo preliminar (idempotente)
  python manage.py gerenciar_termos inicializar

  # Listar o termo e cláusulas em vigor
  python manage.py gerenciar_termos listar

  # Criar uma cláusula diretamente pela linha de comando
  python manage.py gerenciar_termos criar --requisito "coleta_telefone" --desc "Coleta de telefone celular"
  python manage.py gerenciar_termos criar --requisito "termos_uso" --desc "Termos de Uso Obrigatórios" --obrigatoria

  # Criar uma ou mais cláusulas a partir de um arquivo JSON
  python manage.py gerenciar_termos criar --json "caminho/para/clausulas.json"

  # Atualizar uma cláusula existente (cria uma nova versão preservando o histórico)
  python manage.py gerenciar_termos atualizar 2 --desc "Nova descrição da cláusula"
  python manage.py gerenciar_termos atualizar 2 --obrigatoria
  python manage.py gerenciar_termos atualizar 2 --opcional

  # Remover uma ou mais cláusulas pelo ID
  python manage.py gerenciar_termos remover 2
  python manage.py gerenciar_termos remover 2 3
"""

import json
import os
from django.core.management.base import BaseCommand, CommandError

from api.services.termo_consentimento import (
    atualizar_clausula,
    criar_clausula,
    criar_clausulas,
    garantir_termo_inicial,
    listar_clausulas_atuais,
    obter_termo_atual,
    remover_clausula,
    remover_clausulas,
)


class Command(BaseCommand):
    help = 'Gerencia e versiona Termos de Consentimento e Cláusulas da LGPD.'

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(
            dest='acao',
            required=True,
            help='Ação a ser executada',
        )

        # ----------------- SUBCOMANDO: INICIALIZAR -----------------
        subparsers.add_parser(
            'inicializar',
            help='Garante a existência do termo preliminar (Termo #1) com as cláusulas padrão.',
        )

        # ----------------- SUBCOMANDO: LISTAR -----------------
        subparsers.add_parser(
            'listar',
            help='Exibe o termo atual em vigor e todas as suas cláusulas ativas.',
        )

        # ----------------- SUBCOMANDO: CRIAR -----------------
        parser_criar = subparsers.add_parser(
            'criar',
            help='Adiciona uma ou mais cláusulas gerando uma nova versão do Termo.',
        )
        parser_criar.add_argument(
            '--requisito',
            type=str,
            help='Identificador funcional da cláusula (ex: coleta_telefone).',
        )
        parser_criar.add_argument(
            '--desc',
            type=str,
            help='Texto descritivo da cláusula.',
        )
        parser_criar.add_argument(
            '--obrigatoria',
            action='store_true',
            default=False,
            help='Marca a cláusula como obrigatória (padrão: opcional).',
        )
        parser_criar.add_argument(
            '--json',
            dest='caminho_json',
            type=str,
            help='Caminho para um arquivo .json contendo uma cláusula ou lista de cláusulas.',
        )

        # ----------------- SUBCOMANDO: ATUALIZAR -----------------
        parser_atualizar = subparsers.add_parser(
            'atualizar',
            help='Atualiza uma cláusula criando uma nova versão (mantém o histórico íntegro).',
        )
        parser_atualizar.add_argument(
            'id_clausula',
            type=int,
            help='ID da cláusula atual a ser modificada.',
        )
        parser_atualizar.add_argument(
            '--requisito',
            type=str,
            default=None,
            help='Novo requisito funcional.',
        )
        parser_atualizar.add_argument(
            '--desc',
            type=str,
            default=None,
            help='Nova descrição da cláusula.',
        )
        grupo_obrigatoria = parser_atualizar.add_mutually_exclusive_group()
        grupo_obrigatoria.add_argument(
            '--obrigatoria',
            dest='obrigatoria',
            action='store_true',
            default=None,
            help='Define a cláusula como obrigatória.',
        )
        grupo_obrigatoria.add_argument(
            '--opcional',
            dest='obrigatoria',
            action='store_false',
            default=None,
            help='Define a cláusula como opcional.',
        )

        # ----------------- SUBCOMANDO: REMOVER -----------------
        parser_remover = subparsers.add_parser(
            'remover',
            help='Remove uma ou mais cláusulas do termo atual gerando uma nova versão.',
        )
        parser_remover.add_argument(
            'ids',
            type=int,
            nargs='+',
            help='ID(s) da(s) cláusula(s) a remover.',
        )

    def handle(self, *args, **options):
        acao = options.get('acao')

        try:
            if acao == 'inicializar':
                self._handle_inicializar()
            elif acao == 'listar':
                self._handle_listar()
            elif acao == 'criar':
                self._handle_criar(options)
            elif acao == 'atualizar':
                self._handle_atualizar(options)
            elif acao == 'remover':
                self._handle_remover(options)
            else:
                raise CommandError(f'Ação desconhecida: {acao}')
        except ValueError as erro:
            raise CommandError(str(erro))

    def _imprimir_termo_e_clausulas(self, termo, clausulas=None):
        self.stdout.write(
            self.style.SUCCESS(
                f'\n=== Termo #{termo.id_termo} (Criado em: {termo.data_criacao}) ==='
            )
        )
        if clausulas is None:
            clausulas = list(termo.clausulas.all().order_by('id_clausula'))

        if not clausulas:
            self.stdout.write(self.style.WARNING('  Nenhuma cláusula vinculada a este termo.'))
            return

        self.stdout.write(f'Total de cláusulas: {len(clausulas)}')
        for c in clausulas:
            obrigatoria_str = (
                self.style.ERROR('[OBRIGATÓRIA]')
                if c.obrigatoria
                else self.style.NOTICE('[OPCIONAL]')
            )
            self.stdout.write(
                f'  - [ID: {c.id_clausula}] {obrigatoria_str} {c.requisito}: {c.desc}'
            )
        self.stdout.write('')

    def _handle_inicializar(self):
        termo = garantir_termo_inicial()
        clausulas = listar_clausulas_atuais()
        self.stdout.write(
            self.style.SUCCESS('Termo inicial garantido com sucesso (idempotente).')
        )
        self._imprimir_termo_e_clausulas(termo, clausulas)

    def _handle_listar(self):
        termo = obter_termo_atual()
        clausulas = listar_clausulas_atuais()
        self._imprimir_termo_e_clausulas(termo, clausulas)

    def _handle_criar(self, options):
        caminho_json = options.get('caminho_json')
        requisito = options.get('requisito')
        desc = options.get('desc')
        obrigatoria = options.get('obrigatoria', False)

        if caminho_json:
            if not os.path.exists(caminho_json):
                raise CommandError(f'Arquivo JSON não encontrado: {caminho_json}')
            try:
                with open(caminho_json, 'r', encoding='utf-8') as arquivo:
                    conteudo = json.load(arquivo)
            except Exception as erro:
                raise CommandError(f'Falha ao ler o arquivo JSON: {erro}')

            novo_termo = criar_clausulas(conteudo)
            self.stdout.write(self.style.SUCCESS('Cláusulas criadas com sucesso via JSON!'))
            self._imprimir_termo_e_clausulas(novo_termo)
            return

        if not requisito or not desc:
            raise CommandError(
                'Informe --requisito e --desc, ou forneça um arquivo via --json.'
            )

        novo_termo = criar_clausula(
            requisito=requisito,
            desc=desc,
            obrigatoria=obrigatoria,
        )
        self.stdout.write(self.style.SUCCESS('Cláusula criada com sucesso!'))
        self._imprimir_termo_e_clausulas(novo_termo)

    def _handle_atualizar(self, options):
        id_clausula = options['id_clausula']
        requisito = options.get('requisito')
        desc = options.get('desc')
        obrigatoria = options.get('obrigatoria')

        if requisito is None and desc is None and obrigatoria is None:
            raise CommandError(
                'Informe ao menos um campo para atualizar (--requisito, --desc, --obrigatoria ou --opcional).'
            )

        novo_termo = atualizar_clausula(
            clausula_ou_id=id_clausula,
            requisito=requisito,
            desc=desc,
            obrigatoria=obrigatoria,
        )
        self.stdout.write(
            self.style.SUCCESS(f'Cláusula {id_clausula} atualizada em nova versão!')
        )
        self._imprimir_termo_e_clausulas(novo_termo)

    def _handle_remover(self, options):
        ids = options['ids']
        if len(ids) == 1:
            novo_termo = remover_clausula(ids[0])
        else:
            novo_termo = remover_clausulas(ids)

        self.stdout.write(
            self.style.SUCCESS(f'Cláusula(s) {ids} removida(s) em nova versão do termo!')
        )
        self._imprimir_termo_e_clausulas(novo_termo)
