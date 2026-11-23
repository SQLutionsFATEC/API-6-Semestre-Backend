"""Testes unitários das regras de negócio de Termos de Consentimento e Cláusulas."""

import pytest

from api.models import Clausula, ClausulaTermo, Termo
from api.services import TermoConsentimentoService
from api.services.termo_consentimento import (
    REQUISITO_COLETA_NOME,
    REQUISITO_COLETA_USO_EMAIL,
    atualizar_clausula,
    criar_clausula,
    criar_clausulas,
    garantir_termo_inicial,
    listar_clausulas_atuais,
    obter_termo_atual,
    remover_clausula,
    remover_clausulas,
)


@pytest.fixture
def estado_inicial_termo(db):
    """Garante o estado inicial limpo: um Termo com duas cláusulas (1 obrigatória e 1 opcional)."""
    ClausulaTermo.objects.all().delete()
    Termo.objects.all().delete()
    Clausula.objects.all().delete()

    termo_inicial = garantir_termo_inicial()
    clausulas = list(termo_inicial.clausulas.all().order_by('id_clausula'))
    return termo_inicial, clausulas[0], clausulas[1]


@pytest.mark.django_db
def test_estado_preliminar_cria_termo_com_clausula_nome_obrigatoria_e_email_opcional(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo

    assert Termo.objects.count() == 1
    assert Clausula.objects.count() == 2
    assert obter_termo_atual().id_termo == termo_inicial.id_termo

    assert clausula_nome.requisito == REQUISITO_COLETA_NOME
    assert clausula_nome.obrigatoria is True

    assert clausula_email.requisito == REQUISITO_COLETA_USO_EMAIL
    assert clausula_email.obrigatoria is False

    # Chamadas subsequentes a garantir_termo_inicial são idempotentes
    mesmo_termo = garantir_termo_inicial()
    assert mesmo_termo.id_termo == termo_inicial.id_termo
    assert Termo.objects.count() == 1


@pytest.mark.django_db
def test_criacao_de_uma_nova_clausula_gera_nova_versao_do_termo_com_antigas_e_nova(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo

    novo_termo = criar_clausulas(
        {
            'requisito': 'compartilhamento_parceiros',
            'desc': 'Compartilhamento de dados com parceiros',
            'obrigatoria': False,
        }
    )

    assert Termo.objects.count() == 2
    assert novo_termo.id_termo > termo_inicial.id_termo
    assert obter_termo_atual().id_termo == novo_termo.id_termo

    clausulas_atuais = listar_clausulas_atuais()
    assert len(clausulas_atuais) == 3
    ids_atuais = [c.id_clausula for c in clausulas_atuais]
    assert clausula_nome.id_clausula in ids_atuais
    assert clausula_email.id_clausula in ids_atuais

    nova_clausula = [
        c for c in clausulas_atuais
        if c.id_clausula not in (clausula_nome.id_clausula, clausula_email.id_clausula)
    ][0]
    assert nova_clausula.requisito == 'compartilhamento_parceiros'
    assert nova_clausula.desc == 'Compartilhamento de dados com parceiros'
    assert nova_clausula.obrigatoria is False

    # O termo antigo permanece intacto com apenas as 2 cláusulas originais
    assert termo_inicial.clausulas.count() == 2


@pytest.mark.django_db
def test_criacao_de_duas_clausulas_gera_apenas_uma_nova_versao_do_termo(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo

    novo_termo = criar_clausulas(
        [
            {
                'requisito': 'notificacoes_sms',
                'desc': 'Envio de notificações via SMS',
                'obrigatoria': False,
            },
            {
                'requisito': 'auditoria_seguranca',
                'desc': 'Registro de logs para auditoria de segurança',
                'obrigatoria': True,
            },
        ]
    )

    # Deve existir apenas UMA nova versão do termo (total = 2 termos no banco)
    assert Termo.objects.count() == 2
    assert Clausula.objects.count() == 4
    assert obter_termo_atual().id_termo == novo_termo.id_termo
    assert novo_termo.id_termo > termo_inicial.id_termo

    clausulas_atuais = listar_clausulas_atuais()
    assert len(clausulas_atuais) == 4
    requisitos_atuais = [c.requisito for c in clausulas_atuais]
    assert requisitos_atuais == [
        REQUISITO_COLETA_NOME,
        REQUISITO_COLETA_USO_EMAIL,
        'notificacoes_sms',
        'auditoria_seguranca',
    ]


@pytest.mark.django_db
def test_remocao_de_uma_clausula_gera_novo_termo_sem_a_removida_e_preserva_outras(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo

    novo_termo = remover_clausulas(clausula_email.id_clausula)

    assert Termo.objects.count() == 2
    assert novo_termo.id_termo > termo_inicial.id_termo
    assert obter_termo_atual().id_termo == novo_termo.id_termo

    clausulas_atuais = listar_clausulas_atuais()
    assert len(clausulas_atuais) == 1
    assert clausulas_atuais[0].id_clausula == clausula_nome.id_clausula
    assert clausulas_atuais[0].requisito == REQUISITO_COLETA_NOME

    # A cláusula removida NÃO deve ser deletada do banco e continua no termo anterior
    assert Clausula.objects.filter(id_clausula=clausula_email.id_clausula).exists()
    assert termo_inicial.clausulas.count() == 2


@pytest.mark.django_db
def test_remocao_de_duas_clausulas_gera_apenas_uma_nova_versao_do_termo(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo

    novo_termo = remover_clausulas(
        [clausula_nome.id_clausula, clausula_email.id_clausula]
    )

    # Apenas UMA nova versão do termo é criada (total = 2)
    assert Termo.objects.count() == 2
    assert novo_termo.id_termo > termo_inicial.id_termo
    assert obter_termo_atual().id_termo == novo_termo.id_termo

    # Busca pelo termo atual retorna as cláusulas corretas (nenhuma ativa)
    clausulas_atuais = listar_clausulas_atuais()
    assert clausulas_atuais == []

    # As cláusulas antigas e o termo inicial continuam preservados no banco
    assert Clausula.objects.count() == 2
    assert termo_inicial.clausulas.count() == 2


@pytest.mark.django_db
def test_atualizacao_de_clausula_gera_novo_termo_com_nova_clausula_e_preserva_outras(
    estado_inicial_termo,
):
    termo_inicial, clausula_nome, clausula_email = estado_inicial_termo
    desc_original_email = clausula_email.desc

    novo_termo = atualizar_clausula(
        clausula_email.id_clausula,
        desc='Coleta e uso do email para alertas críticos e relatórios',
        obrigatoria=True,
    )

    assert Termo.objects.count() == 2
    assert Clausula.objects.count() == 3
    assert novo_termo.id_termo > termo_inicial.id_termo
    assert obter_termo_atual().id_termo == novo_termo.id_termo

    clausulas_atuais = listar_clausulas_atuais()
    assert len(clausulas_atuais) == 2

    ids_atuais = [c.id_clausula for c in clausulas_atuais]
    assert clausula_nome.id_clausula in ids_atuais
    assert clausula_email.id_clausula not in ids_atuais

    clausula_atualizada = [
        c for c in clausulas_atuais if c.id_clausula != clausula_nome.id_clausula
    ][0]
    assert clausula_atualizada.requisito == REQUISITO_COLETA_USO_EMAIL
    assert (
        clausula_atualizada.desc
        == 'Coleta e uso do email para alertas críticos e relatórios'
    )
    assert clausula_atualizada.obrigatoria is True

    # A cláusula original permanece intacta no banco e vinculada ao termo inicial
    clausula_email.refresh_from_db()
    assert clausula_email.desc == desc_original_email
    assert clausula_email.obrigatoria is False
    assert set(termo_inicial.clausulas.values_list('id_clausula', flat=True)) == {
        clausula_nome.id_clausula,
        clausula_email.id_clausula,
    }


@pytest.mark.django_db
def test_atalhos_e_fachada_service_funcionam_corretamente(estado_inicial_termo):
    _, clausula_nome, _ = estado_inicial_termo

    termo_v2 = criar_clausula('uso_biometria', 'Coleta de biometria', obrigatoria=False)
    assert TermoConsentimentoService.obter_termo_atual().id_termo == termo_v2.id_termo
    assert len(TermoConsentimentoService.listar_clausulas_atuais()) == 3

    termo_v3 = remover_clausula(clausula_nome)
    assert TermoConsentimentoService.obter_termo_atual().id_termo == termo_v3.id_termo
    assert len(TermoConsentimentoService.listar_clausulas_atuais()) == 2

    relacao = ClausulaTermo.objects.filter(id_termo=termo_v3).first()
    assert str(termo_v3) == f'Termo #{termo_v3.id_termo}'
    assert 'Cláusula #' in str(clausula_nome)
    assert f'Termo #{termo_v3.id_termo}' in str(relacao)


@pytest.mark.django_db
def test_validacoes_de_erro_nas_operacoes_de_termo(estado_inicial_termo):
    _, clausula_nome, _ = estado_inicial_termo

    with pytest.raises(ValueError):
        criar_clausulas([])

    with pytest.raises(ValueError):
        criar_clausulas('invalido')

    with pytest.raises(ValueError):
        criar_clausulas(['invalido'])

    with pytest.raises(ValueError):
        criar_clausulas({'requisito': '', 'desc': 'Texto'})

    with pytest.raises(ValueError):
        remover_clausulas([])

    with pytest.raises(ValueError):
        remover_clausulas('invalido')

    with pytest.raises(ValueError):
        remover_clausulas(999999)

    with pytest.raises(ValueError):
        atualizar_clausula(999999, desc='Não existe')

    with pytest.raises(ValueError):
        atualizar_clausula(clausula_nome, requisito='   ')

    with pytest.raises(ValueError):
        atualizar_clausula(True, desc='Booleano inválido como ID')

