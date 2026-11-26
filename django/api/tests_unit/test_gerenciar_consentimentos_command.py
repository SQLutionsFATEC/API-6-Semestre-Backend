"""Testes do comando de consulta de consentimentos."""

import re
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from api.models import Clausula, ClausulaTermo, Consentimento, Termo
from api.services.consentimento import consentir_clausulas, rescindir_consentimento
from api.services.termo_consentimento import criar_clausula, garantir_termo_inicial

ID_USUARIO = 'keycloak-user-uuid'


@pytest.fixture
def estado_inicial(db):
    Consentimento.objects.all().delete()
    ClausulaTermo.objects.all().delete()
    Termo.objects.all().delete()
    Clausula.objects.all().delete()

    termo = garantir_termo_inicial()
    clausula = termo.clausulas.order_by('id_clausula').first()
    return termo, clausula


@pytest.mark.django_db
def test_comando_historico_exibe_aceites_recusas_e_termos(estado_inicial):
    termo_inicial, clausula = estado_inicial
    consentir_clausulas(ID_USUARIO, [clausula.id_clausula])
    termo_seguinte = criar_clausula('nova_clausula', 'Nova cláusula')
    rescindir_consentimento(ID_USUARIO, [clausula.id_clausula])

    saida = StringIO()
    call_command(
        'gerenciar_consentimentos',
        'historico',
        ID_USUARIO,
        stdout=saida,
    )

    texto = saida.getvalue()
    assert 'ACEITO' in texto
    assert 'RECUSADO' in texto
    assert f'Termo #{termo_inicial.id_termo}' in texto
    assert f'Termo #{termo_seguinte.id_termo}' in texto
    assert 'Termos inferidos para o período' in texto


@pytest.mark.django_db
def test_comando_atual_exibe_estado_do_termo_vigente(estado_inicial):
    _, clausula = estado_inicial
    consentir_clausulas(ID_USUARIO, [clausula.id_clausula])
    rescindir_consentimento(ID_USUARIO, [clausula.id_clausula])

    saida = StringIO()
    call_command(
        'gerenciar_consentimentos',
        'atual',
        ID_USUARIO,
        stdout=saida,
        force_color=True,
    )

    texto = saida.getvalue()
    assert re.search(r'\[\x1b\[[0-9;]*mRECUSADO\x1b\[[0-9;]*m\]', texto)
    assert re.search(r'\[\x1b\[[0-9;]*mSEM RESPOSTA\x1b\[[0-9;]*m\]', texto)


@pytest.mark.django_db
def test_comando_registra_aceite_e_recusa_para_lista_de_clausulas(estado_inicial):
    termo, _ = estado_inicial
    clausulas = list(termo.clausulas.order_by('id_clausula'))
    saida_aceite = StringIO()

    call_command(
        'gerenciar_consentimentos',
        'registrar',
        ID_USUARIO,
        'aceitar',
        str(clausulas[0].id_clausula),
        str(clausulas[1].id_clausula),
        stdout=saida_aceite,
    )

    assert Consentimento.objects.filter(
        id_usuario=ID_USUARIO,
        acordo=True,
    ).count() == 2
    assert 'Decisão "aceitar" registrada para 2 cláusula(s)' in saida_aceite.getvalue()

    saida_recusa = StringIO()
    call_command(
        'gerenciar_consentimentos',
        'registrar',
        ID_USUARIO,
        'recusar',
        str(clausulas[1].id_clausula),
        stdout=saida_recusa,
    )

    assert Consentimento.objects.filter(
        id_usuario=ID_USUARIO,
        id_clausula=clausulas[1],
        acordo=False,
    ).count() == 1
    assert 'Decisão "recusar" registrada para 1 cláusula(s)' in saida_recusa.getvalue()


@pytest.mark.django_db
def test_comando_registrar_retorna_erro_para_clausula_fora_do_termo(estado_inicial):
    _, clausula = estado_inicial

    with pytest.raises(CommandError, match='não encontrada'):
        call_command(
            'gerenciar_consentimentos',
            'registrar',
            ID_USUARIO,
            'aceitar',
            str(clausula.id_clausula + 100),
        )
