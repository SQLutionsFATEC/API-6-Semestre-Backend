"""Testes unitários da modelagem e regras de negócio de Consentimento do Usuário."""

from datetime import timedelta

import pytest
from django.utils import timezone

from api.models import Clausula, Consentimento, Termo
from api.services.consentimento import (
    ConsentimentoService,
    consentir_clausulas,
    obter_consentimentos_usuario,
    obter_historico_consentimentos_usuario,
    rescindir_consentimento,
    verificar_consentimento,
)
from api.services.termo_consentimento import (
    atualizar_clausula,
    criar_clausula,
    garantir_termo_inicial,
    remover_clausula,
)

ID_USUARIO = "uuid-user-teste-123"


@pytest.fixture
def estado_inicial(db):
    """Garante o estado inicial limpo e retorna o termo e suas 2 cláusulas."""
    Clausula.objects.all().delete()
    Termo.objects.all().delete()
    Consentimento.objects.all().delete()

    termo = garantir_termo_inicial()
    clausulas = list(termo.clausulas.all().order_by('id_clausula'))

    return {
        'termo': termo,
        'clausula_obrigatoria': clausulas[0],  # coleta_nome (obrigatória)
        'clausula_opcional': clausulas[1],  # coleta_uso_email (opcional)
    }


@pytest.mark.django_db
def test_consentimento_aos_dois_termos_retorna_ambos_aceitos(estado_inicial):
    c_obrig = estado_inicial['clausula_obrigatoria']
    c_opc = estado_inicial['clausula_opcional']

    # Usuário consente aos dois
    consentir_clausulas(ID_USUARIO, [c_obrig.id_clausula, c_opc.id_clausula])

    # Valida o estado atual via serviço
    status_atual = obter_consentimentos_usuario(ID_USUARIO)

    assert len(status_atual) == 2
    for item in status_atual:
        assert item['acordo'] is True

    # Valida a verificação pontual por requisito
    assert verificar_consentimento(ID_USUARIO, c_obrig.requisito) is True
    assert verificar_consentimento(ID_USUARIO, c_opc.requisito) is True


@pytest.mark.django_db
def test_consentimento_e_revogacao_preserva_historico_e_retorna_negado(estado_inicial):
    c_obrig = estado_inicial['clausula_obrigatoria']
    c_opc = estado_inicial['clausula_opcional']

    # 1. Consente aos dois
    consentir_clausulas(ID_USUARIO, [c_obrig.id_clausula, c_opc.id_clausula])

    # 2. Revoga o consentimento a ambos
    rescindir_consentimento(ID_USUARIO, [c_obrig.id_clausula, c_opc.id_clausula])

    # O banco deve ter 4 registros (2 aceites antigos + 2 revogações recentes)
    assert Consentimento.objects.count() == 4

    # Valida que o estado atual agora é negado (False) para ambos
    status_atual = obter_consentimentos_usuario(ID_USUARIO)
    assert len(status_atual) == 2
    for item in status_atual:
        assert item['acordo'] is False

    assert verificar_consentimento(ID_USUARIO, c_obrig.requisito) is False
    assert verificar_consentimento(ID_USUARIO, c_opc.requisito) is False


@pytest.mark.django_db
def test_historico_associa_eventos_aos_termos_do_periodo(estado_inicial):
    termo_inicial = estado_inicial['termo']
    clausula = estado_inicial['clausula_obrigatoria']
    agora = timezone.now()
    inicio = agora - timedelta(days=4)
    aceite = agora - timedelta(days=3, hours=12)
    meio = agora - timedelta(days=3)
    recusa = agora - timedelta(days=2, hours=12)
    fim = agora - timedelta(days=2)

    Termo.objects.filter(pk=termo_inicial.pk).update(data_criacao=inicio)
    consentir_clausulas(ID_USUARIO, [clausula.id_clausula])
    Consentimento.objects.filter(
        id_usuario=ID_USUARIO,
        id_clausula=clausula,
        acordo=True,
    ).update(timestamp_consentimento=aceite)

    termo_intermediario = criar_clausula('nova_intermediaria', 'Cláusula nova')
    Termo.objects.filter(pk=termo_intermediario.pk).update(data_criacao=meio)
    rescindir_consentimento(ID_USUARIO, [clausula.id_clausula])
    Consentimento.objects.filter(
        id_usuario=ID_USUARIO,
        id_clausula=clausula,
        acordo=False,
    ).update(timestamp_consentimento=recusa)

    termo_final = criar_clausula('nova_final', 'Outra cláusula')
    Termo.objects.filter(pk=termo_final.pk).update(data_criacao=fim)

    historico = obter_historico_consentimentos_usuario(ID_USUARIO)

    assert len(historico) == 2
    assert historico[0]['consentimento'].acordo is True
    assert historico[0]['fim_periodo'] == recusa
    assert [termo.id_termo for termo in historico[0]['termos']] == [
        termo_inicial.id_termo,
        termo_intermediario.id_termo,
    ]
    assert historico[1]['consentimento'].acordo is False
    assert historico[1]['fim_periodo'] is None
    assert [termo.id_termo for termo in historico[1]['termos']] == [
        termo_intermediario.id_termo,
        termo_final.id_termo,
    ]


@pytest.mark.django_db
def test_adicionar_nova_clausula_preserva_consentimentos_antigos(estado_inicial):
    c_obrig = estado_inicial['clausula_obrigatoria']
    c_opc = estado_inicial['clausula_opcional']

    # 1. Usuário consente aos dois termos originais
    consentir_clausulas(ID_USUARIO, [c_obrig.id_clausula, c_opc.id_clausula])

    # 2. Admin adiciona uma nova cláusula (gera novo Termo)
    criar_clausula('nova_func', 'Nova Funcionalidade', obrigatoria=False)

    # 3. Busca o estado atual do usuário
    status_atual = obter_consentimentos_usuario(ID_USUARIO)

    # Devem existir 3 itens no retorno (as 2 antigas e a nova)
    assert len(status_atual) == 3

    # As cláusulas antigas DEVEM estar preservadas como True
    antigas = [i for i in status_atual if i['clausula'].id_clausula in (c_obrig.id_clausula, c_opc.id_clausula)]
    for item in antigas:
        assert item['acordo'] is True

    # A nova cláusula não possui resposta (None)
    nova = next(i for i in status_atual if i['requisito'] == 'nova_func')
    assert nova['acordo'] is None


@pytest.mark.django_db
def test_remover_clausula_preserva_consentimento_da_restante(estado_inicial):
    c_obrig = estado_inicial['clausula_obrigatoria']
    c_opc = estado_inicial['clausula_opcional']

    # 1. Usuário consente aos dois termos originais
    consentir_clausulas(ID_USUARIO, [c_obrig.id_clausula, c_opc.id_clausula])

    # 2. Admin remove a cláusula opcional (gera novo Termo sem ela)
    remover_clausula(c_opc.id_clausula)

    # 3. Busca o estado atual do usuário
    status_atual = obter_consentimentos_usuario(ID_USUARIO)

    # O retorno deve ter apenas 1 item (a cláusula obrigatória que restou)
    assert len(status_atual) == 1
    assert status_atual[0]['clausula'].id_clausula == c_obrig.id_clausula
    assert status_atual[0]['acordo'] is True

    # A verificação pontual da cláusula removida no termo atual deve retornar False
    assert verificar_consentimento(ID_USUARIO, c_opc.requisito) is False


@pytest.mark.django_db
def test_validacoes_de_erro_no_consentimento(estado_inicial):
    c_obrig = estado_inicial['clausula_obrigatoria']

    with pytest.raises(ValueError):
        consentir_clausulas("", [c_obrig.id_clausula])

    with pytest.raises(ValueError):
        consentir_clausulas(ID_USUARIO, [])

    with pytest.raises(ValueError):
        consentir_clausulas(ID_USUARIO, "invalido")

    with pytest.raises(ValueError):
        consentir_clausulas(ID_USUARIO, 99999)  # Cláusula não existe no termo atual