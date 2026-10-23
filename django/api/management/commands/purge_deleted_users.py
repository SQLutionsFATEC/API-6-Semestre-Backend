"""Anonimiza no Keycloak usuários que constam no banco de tombstones.

Este comando é a garantia do direito ao esquecimento após uma restauração de
backup: o restore script restaura o banco do Keycloak, sobe o serviço e então
executa este comando. Todo usuário cujo hash SHA-256 esteja em um tombstone
confirmado é anonimizado novamente; tombstones pendentes são ignorados, pois
indicam uma anonimização que o Keycloak não confirmou. Com ``--verificar``, o
comando relê o Keycloak e falha (exit code 1) se algum usuário tombstoned
ainda tiver dados pessoais.

Uso:
    python manage.py purge_deleted_users --verificar --aguardar 120
    python manage.py purge_deleted_users --dry-run
"""

import time

import requests
from django.core.management.base import BaseCommand, CommandError

from api.services import keycloak_admin
from api.services.delecao_usuario import (
    hash_id_usuario,
    listar_hashes_usuarios_deletados,
)

TAMANHO_PAGINA = 100
INTERVALO_ESPERA = 2


class Command(BaseCommand):
    help = (
        'Anonimiza no Keycloak os usuários presentes no banco de tombstones '
        '(usado após restaurar um backup) e, opcionalmente, verifica que '
        'nenhum deles ainda tenha dados pessoais.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas lista quantos usuários seriam anonimizados; não altera o Keycloak.',
        )
        parser.add_argument(
            '--verificar',
            action='store_true',
            help=(
                'Relê o Keycloak após a anonimização e falha se algum usuário '
                'tombstoned ainda tiver dados pessoais.'
            ),
        )
        parser.add_argument(
            '--aguardar',
            type=int,
            default=0,
            metavar='SEGUNDOS',
            help='Tempo máximo para esperar o Keycloak ficar disponível (padrão: 0).',
        )

    def handle(self, *args, **options):
        hashes = set(listar_hashes_usuarios_deletados())
        if not hashes:
            self.stdout.write(
                'Nenhum usuário tombstoned confirmado; nada a anonimizar.'
            )
            return

        usuarios = self._listar_usuarios(options['aguardar'])
        encontrados = [
            usuario
            for usuario in usuarios
            if self._hash_do_usuario(usuario) in hashes
        ]

        if options['dry_run']:
            self.stdout.write(
                f'{len(encontrados)} usuário(s) seriam anonimizados no Keycloak.'
            )
            return

        anonimizados = 0
        for usuario in encontrados:
            id_usuario = usuario.get('id')
            try:
                keycloak_admin.anonimizar_usuario(
                    id_usuario, sufixo=self._hash_do_usuario(usuario)
                )
            except keycloak_admin.KeycloakAdminException as erro:
                # 404 significa que o usuário já não existe: não há dados
                # pessoais a anonimizar, então a operação é idempotente.
                if erro.codigo_status != 404:
                    raise CommandError(
                        'Falha ao anonimizar usuário tombstoned do Keycloak: '
                        f'{erro}'
                    )
                continue
            anonimizados += 1

        self.stdout.write(
            f'{anonimizados} usuário(s) anonimizado(s) no Keycloak restaurado.'
        )

        if options['verificar']:
            self._verificar(hashes, options['aguardar'])

    def _listar_usuarios(self, aguardar=0):
        """Lista todos os usuários do Keycloak, com paginação completa.

        A lista completa é obtida antes de qualquer anonimização, para que a
        paginação não pule usuários durante o processo. Se ``aguardar`` > 0,
        tenta novamente enquanto o Keycloak estiver iniciando.
        """
        limite = time.monotonic() + max(aguardar, 0)
        while True:
            try:
                return self._coletar_paginas()
            except (
                keycloak_admin.KeycloakAdminException,
                requests.RequestException,
            ) as erro:
                if not self._erro_temporario(erro) or time.monotonic() >= limite:
                    raise CommandError(f'Falha ao consultar o Keycloak: {erro}')
                time.sleep(INTERVALO_ESPERA)

    def _coletar_paginas(self):
        usuarios = []
        inicio = 0
        while True:
            pagina = keycloak_admin.listar_usuarios(
                inicio=inicio, maximo=TAMANHO_PAGINA
            )
            if not pagina:
                break
            usuarios.extend(pagina)
            inicio += TAMANHO_PAGINA
        return usuarios

    def _verificar(self, hashes, aguardar=0):
        usuarios = self._listar_usuarios(aguardar)
        restantes = [
            usuario.get('id')
            for usuario in usuarios
            if self._hash_do_usuario(usuario) in hashes
            and not keycloak_admin.usuario_esta_anonimizado(
                usuario, sufixo=self._hash_do_usuario(usuario)
            )
        ]
        if restantes:
            raise CommandError(
                'VERIFICAÇÃO FALHOU: usuário(s) tombstoned ainda possuem '
                f'dados pessoais no Keycloak restaurado ({len(restantes)}).'
            )
        self.stdout.write(
            self.style.SUCCESS(
                'Verificação concluída: nenhum usuário tombstoned permanece '
                'com dados pessoais.'
            )
        )

    @staticmethod
    def _hash_do_usuario(usuario):
        id_usuario = (usuario or {}).get('id')
        if not id_usuario:
            return None
        return hash_id_usuario(id_usuario)

    @staticmethod
    def _erro_temporario(erro):
        if isinstance(erro, requests.RequestException):
            return True
        codigo = getattr(erro, 'codigo_status', None)
        return codigo is None or codigo >= 500
