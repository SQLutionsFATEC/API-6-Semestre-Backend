"""Testes do comando de consulta de consentimentos."""

from io import StringIO

import pytest
from django.core.management import call_command

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
    )

    assert '[RECUSADO]' in saida.getvalue()
    assert '[SEM RESPOSTA]' in saida.getvalue()
