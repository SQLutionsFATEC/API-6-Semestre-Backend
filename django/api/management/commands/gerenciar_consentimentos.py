"""Comandos para consultar o histórico e o estado atual dos consentimentos.

Exemplos:
  python manage.py gerenciar_consentimentos historico <id_usuario>
  python manage.py gerenciar_consentimentos atual <id_usuario>
  python manage.py gerenciar_consentimentos registrar <id_usuario> aceitar <id_clausula> [<id_clausula> ...]
  python manage.py gerenciar_consentimentos registrar <id_usuario> recusar <id_clausula> [<id_clausula> ...]

``id_usuario`` é o UUID/ID do usuário no Keycloak, o mesmo valor persistido
nos registros de consentimento. Use o campo ``id`` do usuário no Keycloak
(ou o claim ``sub``), não o username ou e-mail, que podem ser alterados.
Os IDs informados para ``registrar`` são de cláusulas do termo atual.
"""

from django.core.management.base import BaseCommand, CommandError

from api.services.consentimento import (
    consentir_clausulas,
    obter_consentimentos_usuario,
    obter_historico_consentimentos_usuario,
    rescindir_consentimento,
)
from api.services.termo_consentimento import obter_termo_atual


class Command(BaseCommand):
    help = 'Consulta e atualiza consentimentos por usuário.'

    def add_arguments(self, parser):
        """Registra consultas e atualizações de consentimento."""
        subparsers = parser.add_subparsers(
            dest='acao',
            required=True,
            help='Ação de consentimento a executar',
        )

        parser_historico = subparsers.add_parser(
            'historico',
            help='Exibe aceites/recusas e os termos associados a cada período.',
        )
        parser_historico.add_argument(
            'id_usuario',
            help='ID/UUID do usuário no Keycloak (claim sub; não use username/e-mail).',
        )

        parser_atual = subparsers.add_parser(
            'atual',
            help='Exibe o estado de consentimento no termo atualmente vigente.',
        )
        parser_atual.add_argument(
            'id_usuario',
            help='ID/UUID do usuário no Keycloak (claim sub; não use username/e-mail).',
        )

        parser_registrar = subparsers.add_parser(
            'registrar',
            help='Aceita ou recusa uma ou mais cláusulas do termo atual.',
        )
        parser_registrar.add_argument(
            'id_usuario',
            help='ID/UUID do usuário no Keycloak (claim sub; não use username/e-mail).',
        )
        parser_registrar.add_argument(
            'decisao',
            choices=('aceitar', 'recusar'),
            help='Decisão a registrar para as cláusulas informadas.',
        )
        parser_registrar.add_argument(
            'id_clausulas',
            metavar='ID_CLAUSULA',
            type=int,
            nargs='+',
            help='Um ou mais IDs de cláusulas pertencentes ao termo atual.',
        )

    def handle(self, *args, **options):
        """Encaminha a execução à ação selecionada."""
        acao = options['acao']
        id_usuario = options['id_usuario']

        if acao == 'historico':
            self._handle_historico(id_usuario)
        elif acao == 'atual':
            self._handle_atual(id_usuario)
        elif acao == 'registrar':
            self._handle_registrar(
                id_usuario,
                options['decisao'],
                options['id_clausulas'],
            )

    def _handle_registrar(self, id_usuario, decisao, id_clausulas):
        """Registra a mesma decisão para as cláusulas fornecidas."""
        registrar = (
            consentir_clausulas if decisao == 'aceitar' else rescindir_consentimento
        )
        try:
            registros = registrar(id_usuario, id_clausulas)
        except ValueError as erro:
            raise CommandError(str(erro)) from erro

        if registros:
            estilo = self.style.SUCCESS if decisao == 'aceitar' else self.style.ERROR
            self.stdout.write(
                estilo(
                    f'Decisão "{decisao}" registrada para {len(registros)} '
                    f'cláusula(s) do usuário {id_usuario}.'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'Nenhuma alteração necessária para as cláusulas do usuário '
                    f'{id_usuario}.'
                )
            )

    def _handle_historico(self, id_usuario):
        """Exibe decisões de consentimento, períodos e termos inferidos."""
        historico = obter_historico_consentimentos_usuario(id_usuario)
        if not historico:
            self.stdout.write(
                self.style.WARNING(
                    'Nenhum aceite ou recusa encontrado para esse usuário.'
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f'Histórico de consentimento do usuário {id_usuario}:'
            )
        )
        for item in historico:
            evento = item['consentimento']
            status = (
                self.style.SUCCESS('ACEITO')
                if evento.acordo
                else self.style.ERROR('RECUSADO')
            )
            self.stdout.write(
                f'\n[{evento.timestamp_consentimento}] {status} — '
                f'Cláusula #{evento.id_clausula_id} '
                f'({evento.id_clausula.requisito}): {evento.id_clausula.desc}'
            )
            fim_periodo = item['fim_periodo']
            if fim_periodo is None:
                self.stdout.write('  Período: sem nova decisão registrada.')
            else:
                self.stdout.write(
                    f'  Período: até {fim_periodo} (exclusivo).'
                )

            if not item['termos']:
                self.stdout.write('  Termos inferidos para o período: nenhum.')
                continue

            self.stdout.write('  Termos inferidos para o período:')
            for termo in item['termos']:
                self.stdout.write(
                    f'    - Termo #{termo.id_termo} '
                    f'(criado em {termo.data_criacao})'
                )

    def _handle_atual(self, id_usuario):
        """Exibe o estado de consentimento das cláusulas do termo vigente."""
        termo = obter_termo_atual()
        estados = obter_consentimentos_usuario(id_usuario)

        self.stdout.write(
            self.style.SUCCESS(
                f'Termo atual #{termo.id_termo} (criado em {termo.data_criacao}) '
                f'para o usuário {id_usuario}:'
            )
        )
        if not estados:
            self.stdout.write(
                self.style.WARNING('  O termo atual não possui cláusulas.')
            )
            return

        for item in estados:
            acordo = item['acordo']
            status = (
                self.style.SUCCESS('ACEITO')
                if acordo is True
                else self.style.ERROR('RECUSADO')
                if acordo is False
                else self.style.NOTICE('SEM RESPOSTA')
            )
            clausula = item['clausula']
            self.stdout.write(
                f'  - [{status}] Cláusula #{clausula.id_clausula} '
                f'({clausula.requisito}): {clausula.desc}'
            )
