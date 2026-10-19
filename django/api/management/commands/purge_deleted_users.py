"""Remove do Keycloak usuários que constam no banco de tombstones.

Este comando é a garantia do direito ao esquecimento após uma restauração de
backup: o restore script restaura o banco do Keycloak, sobe o serviço e então
executa este comando. Todo usuário cujo hash SHA-256 esteja no banco
independente de tombstones é deletado novamente. Com ``--verificar``, o
comando relê o Keycloak e falha (exit code 1) se algum usuário deletado
continuar existindo.

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
        'Deleta do Keycloak os usuários presentes no banco de tombstones '
        '(usado após restaurar um backup) e, opcionalmente, verifica que '
        'nenhum deles voltou.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas lista quantos usuários seriam deletados; não altera o Keycloak.',
        )
        parser.add_argument(
            '--verificar',
            action='store_true',
            help='Relê o Keycloak após a purga e falha se algum usuário deletado permanecer.',
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
            self.stdout.write('Nenhum usuário deletado registrado; nada a purgar.')
            return

        usuarios = self._listar_usuarios(options['aguardar'])
        encontrados = [
            usuario
            for usuario in usuarios
            if self._hash_do_usuario(usuario) in hashes
        ]

        if options['dry_run']:
            self.stdout.write(
                f'{len(encontrados)} usuário(s) deletado(s) seriam removidos do Keycloak.'
            )
            return

        removidos = 0
        for usuario in encontrados:
            id_usuario = usuario.get('id')
            try:
                keycloak_admin.deletar_usuario(id_usuario)
            except keycloak_admin.KeycloakAdminException as erro:
                # 404 significa que o usuário já não existe: o objetivo foi
                # cumprido, então a operação é idempotente.
                if erro.codigo_status != 404:
                    raise CommandError(
                        'Falha ao deletar usuário tombstoned do Keycloak: '
                        f'{erro}'
                    )
                continue
            removidos += 1

        self.stdout.write(
            f'{removidos} usuário(s) deletado(s) removido(s) do Keycloak restaurado.'
        )

        if options['verificar']:
            self._verificar(hashes, options['aguardar'])

    def _listar_usuarios(self, aguardar=0):
        """Lista todos os usuários do Keycloak, com paginação completa.

        A lista completa é obtida antes de qualquer deleção, para que a
        paginação não pule usuários quando o conjunto diminui durante o
        processo. Se ``aguardar`` > 0, tenta novamente enquanto o Keycloak
        estiver iniciando.
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
        ]
        if restantes:
            raise CommandError(
                'VERIFICAÇÃO FALHOU: usuário(s) deletado(s) ainda existem no '
                f'Keycloak restaurado ({len(restantes)}).'
            )
        self.stdout.write(
            self.style.SUCCESS(
                'Verificação concluída: nenhum usuário deletado foi restaurado.'
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
