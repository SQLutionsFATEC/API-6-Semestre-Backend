#!/usr/bin/env python3
"""Busca um usuário no Keycloak pela API Django e imprime seu ID."""

import argparse
import getpass
import os
import sys

import requests


def obter_token(keycloak_url, realm, client_id, username, password):
    url = (
        f'{keycloak_url.rstrip("/")}/realms/{realm}'
        '/protocol/openid-connect/token'
    )
    resposta = requests.post(
        url,
        data={
            'grant_type': 'password',
            'client_id': client_id,
            'username': username,
            'password': password,
        },
        timeout=15,
    )
    if resposta.status_code in (400, 401):
        raise RuntimeError(
            'Não foi possível autenticar o operador. Confira as credenciais '
            'e se o Direct Access Grants está habilitado no client.'
        )
    resposta.raise_for_status()

    token = resposta.json().get('access_token')
    if not token:
        raise RuntimeError('A resposta do Keycloak não contém access_token.')
    return token


def buscar_usuario(api_url, token, username):
    resposta = requests.get(
        f'{api_url.rstrip("/")}/api/usuarios/',
        params={'busca': username},
        headers={'Authorization': f'Bearer {token}'},
        timeout=15,
    )
    if resposta.status_code == 401:
        raise RuntimeError('A API rejeitou o token de autenticação.')
    if resposta.status_code == 403:
        raise RuntimeError(
            'O usuário operador não tem permissão para listar usuários.'
        )
    resposta.raise_for_status()

    usuarios = resposta.json()
    if not isinstance(usuarios, list):
        raise RuntimeError('A API retornou um formato inesperado.')

    return usuarios


def main():
    parser = argparse.ArgumentParser(
        description='Busca um usuário pelo username e exibe seu ID do Keycloak.'
    )
    parser.add_argument('username', help='Username exato do usuário a buscar')
    args = parser.parse_args()

    operador = os.getenv('KEYCLOAK_OPERATOR_USERNAME', 'operador')
    senha = "operador"#os.getenv('KEYCLOAK_OPERATOR_PASSWORD')
    if senha is None:
        senha = getpass.getpass(f'Senha de {operador}: ')

    keycloak_url = os.getenv('KEYCLOAK_URL', 'http://localhost:8080')
    realm = os.getenv('KEYCLOAK_REALM', 'sqlutions')
    client_id = os.getenv('KEYCLOAK_CLIENT_ID', 'frontend')
    api_url = os.getenv('API_BASE_URL', 'http://localhost:8000')

    try:
        token = obter_token(
            keycloak_url, realm, client_id, operador, senha
        )
        usuarios = buscar_usuario(api_url, token, args.username)
    except requests.RequestException as erro:
        print(f'Falha de comunicação: {erro}', file=sys.stderr)
        return 1
    except RuntimeError as erro:
        print(str(erro), file=sys.stderr)
        return 1

    exatos = [
        usuario
        for usuario in usuarios
        if usuario.get('username') == args.username
    ]
    if len(exatos) == 1:
        id_usuario = exatos[0].get('id')
        if id_usuario:
            print(id_usuario)
            return 0
        print('A API retornou o usuário sem ID.', file=sys.stderr)
    elif len(exatos) > 1:
        print('Mais de um usuário corresponde exatamente ao username:', file=sys.stderr)
        for usuario in exatos:
            print(usuario.get('id', '(sem ID)'), file=sys.stderr)
    elif usuarios:
        print('Nenhum username exato; resultados parciais:', file=sys.stderr)
        for usuario in usuarios:
            print(
                f"- {usuario.get('username', '(sem username)')}: "
                f"{usuario.get('id', '(sem ID)')}",
                file=sys.stderr,
            )
    else:
        print(f'Usuário não encontrado: {args.username}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
