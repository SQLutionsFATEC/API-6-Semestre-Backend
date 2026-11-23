"""Testes unitários para o comando gerenciar_termos."""

import json
from io import StringIO
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from api.models import Clausula, ClausulaTermo, Termo
from api.services.termo_consentimento import garantir_termo_inicial


@pytest.fixture(autouse=True)
def _limpar_tabelas(db):
    """Limpa tabelas antes de cada teste."""
    ClausulaTermo.objects.all().delete()
    Termo.objects.all().delete()
    Clausula.objects.all().delete()


@pytest.mark.django_db
def test_comando_inicializar():
    out = StringIO()
    call_command('gerenciar_termos', 'inicializar', stdout=out)
    saida = out.getvalue()

    assert 'Termo inicial garantido' in saida
    assert 'Termo #' in saida
    assert 'coleta_nome' in saida
    assert 'coleta_uso_email' in saida


@pytest.mark.django_db
def test_comando_listar_inicializa_e_exibe_termo():
    out = StringIO()
    call_command('gerenciar_termos', 'listar', stdout=out)
    saida = out.getvalue()

    assert 'Termo #' in saida
    assert 'coleta_nome' in saida
    assert 'coleta_uso_email' in saida


@pytest.mark.django_db
def test_comando_criar_clausula_via_argumentos():
    termo_inicial = garantir_termo_inicial()
    out = StringIO()
    call_command(
        'gerenciar_termos',
        'criar',
        '--requisito',
        'coleta_telefone',
        '--desc',
        'Coleta de telefone celular',
        '--obrigatoria',
        stdout=out,
    )
    saida = out.getvalue()

    termo_2 = Termo.objects.order_by('-id_termo').first()
    assert termo_2.id_termo > termo_inicial.id_termo
    assert f'Termo #{termo_2.id_termo}' in saida
    assert 'coleta_telefone' in saida
    assert '[OBRIGATÓRIA]' in saida
    assert termo_2.clausulas.count() == 3


@pytest.mark.django_db
def test_comando_criar_clausulas_via_json(tmp_path):
    termo_inicial = garantir_termo_inicial()
    arquivo_json = tmp_path / 'clausulas.json'
    dados = [
        {'requisito': 'item_1', 'desc': 'Desc 1', 'obrigatoria': True},
        {'requisito': 'item_2', 'desc': 'Desc 2', 'obrigatoria': False},
    ]
    arquivo_json.write_text(json.dumps(dados), encoding='utf-8')

    out = StringIO()
    call_command(
        'gerenciar_termos',
        'criar',
        '--json',
        str(arquivo_json),
        stdout=out,
    )
    saida = out.getvalue()

    termo_2 = Termo.objects.order_by('-id_termo').first()
    assert termo_2.id_termo > termo_inicial.id_termo
    assert f'Termo #{termo_2.id_termo}' in saida
    assert 'item_1' in saida
    assert 'item_2' in saida
    assert termo_2.clausulas.count() == 4


@pytest.mark.django_db
def test_comando_criar_sem_argumentos_lanca_erro():
    garantir_termo_inicial()
    with pytest.raises(CommandError, match='Informe --requisito e --desc'):
        call_command('gerenciar_termos', 'criar')


@pytest.mark.django_db
def test_comando_atualizar_clausula():
    termo_inicial = garantir_termo_inicial()
    clausula_email = termo_inicial.clausulas.get(requisito='coleta_uso_email')

    out = StringIO()
    call_command(
        'gerenciar_termos',
        'atualizar',
        clausula_email.id_clausula,
        '--desc',
        'Nova descrição de email atualizada',
        '--obrigatoria',
        stdout=out,
    )
    saida = out.getvalue()

    termo_2 = Termo.objects.order_by('-id_termo').first()
    assert termo_2.id_termo > termo_inicial.id_termo
    assert f'Termo #{termo_2.id_termo}' in saida
    assert 'Nova descrição de email atualizada' in saida

    clausula_atualizada = termo_2.clausulas.get(requisito='coleta_uso_email')
    assert clausula_atualizada.desc == 'Nova descrição de email atualizada'
    assert clausula_atualizada.obrigatoria is True
    assert clausula_atualizada.id_clausula != clausula_email.id_clausula


@pytest.mark.django_db
def test_comando_remover_uma_clausula():
    termo_inicial = garantir_termo_inicial()
    clausula_email = termo_inicial.clausulas.get(requisito='coleta_uso_email')

    out = StringIO()
    call_command(
        'gerenciar_termos',
        'remover',
        clausula_email.id_clausula,
        stdout=out,
    )
    saida = out.getvalue()

    termo_2 = Termo.objects.order_by('-id_termo').first()
    assert termo_2.id_termo > termo_inicial.id_termo
    assert f'Termo #{termo_2.id_termo}' in saida
    assert termo_2.clausulas.count() == 1
    assert not termo_2.clausulas.filter(id_clausula=clausula_email.id_clausula).exists()


@pytest.mark.django_db
def test_comando_remover_multiplas_clausulas():
    termo_inicial = garantir_termo_inicial()
    ids = list(termo_inicial.clausulas.values_list('id_clausula', flat=True))

    out = StringIO()
    call_command(
        'gerenciar_termos',
        'remover',
        *ids,
        stdout=out,
    )
    saida = out.getvalue()

    termo_2 = Termo.objects.order_by('-id_termo').first()
    assert termo_2.id_termo > termo_inicial.id_termo
    assert f'Termo #{termo_2.id_termo}' in saida
    assert termo_2.clausulas.count() == 0
