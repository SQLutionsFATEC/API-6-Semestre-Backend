"""Serviço de gerenciamento do Histórico de Consentimento do Usuário.

Este módulo implementa a API interna (não HTTP) que permite:
  - Consultar o estado atual de consentimento de um usuário;
  - Consultar o histórico de aceites/recusas e inferir os termos vigentes em cada período;
  - Validar se o usuário consente com um requisito específico;
  - Registrar o consentimento ou a revogação de uma ou mais cláusulas.

A tabela de consentimentos é Append-Only: nunca há UPDATE nem DELETE. A cada
ação, um novo registro com timestamp é inserido. O estado atual é definido
pelo registro mais recente para cada par (usuário, cláusula).
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict

from django.db import transaction
from django.db.models import OuterRef, Subquery

from api.models import Clausula, Consentimento, Termo
from api.services.termo_consentimento import obter_termo_atual, _extrair_id_clausula


@transaction.atomic
def registrar_consentimento(id_usuario, clausulas_ou_ids, acordo):
    """Registra consentimento (True) ou revogação (False) para uma ou mais cláusulas.

    Retorna a lista de objetos Consentimento recém-criados.
    """
    if not id_usuario:
        raise ValueError('O ID do usuário é obrigatório.')

    # Normaliza a entrada para uma lista de IDs
    if isinstance(clausulas_ou_ids, (int, Clausula)) and not isinstance(clausulas_ou_ids, bool):
        itens = [clausulas_ou_ids]
    elif isinstance(clausulas_ou_ids, (list, tuple, set)):
        itens = list(clausulas_ou_ids)
    else:
        raise ValueError('Informe um ID/Cláusula ou uma coleção de IDs/Cláusulas.')

    if not itens:
        raise ValueError('Informe ao menos uma cláusula.')

    ids_para_registrar = {_extrair_id_clausula(item) for item in itens}

    # Valida se as cláusulas pertencem ao termo em vigor
    termo_atual = obter_termo_atual()
    ids_atuais = set(termo_atual.clausulas.values_list('id_clausula', flat=True))

    ids_invalidos = ids_para_registrar - ids_atuais
    if ids_invalidos:
        raise ValueError(
            f'Cláusula(s) não encontrada(s) no termo atual: {sorted(ids_invalidos)}'
        )

    estados_atuais = {}
    consentimentos_anteriores = (
        Consentimento.objects.filter(
            id_usuario=id_usuario,
            id_clausula_id__in=ids_para_registrar,
        )
        .order_by(
            'id_clausula_id',
            '-timestamp_consentimento',
            '-id_consentimento',
        )
        .values_list('id_clausula_id', 'acordo')
    )
    for id_clausula, estado in consentimentos_anteriores:
        estados_atuais.setdefault(id_clausula, estado)

    registros = [
        Consentimento(
            id_usuario=id_usuario,
            id_clausula_id=id_clausula,
            acordo=acordo,
        )
        for id_clausula in ids_para_registrar
        if estados_atuais.get(id_clausula) != acordo
    ]

    return Consentimento.objects.bulk_create(registros) if registros else []


def consentir_clausulas(id_usuario, clausulas_ou_ids):
    """Atalho para registrar consentimento (acordo=True)."""
    return registrar_consentimento(id_usuario, clausulas_ou_ids, acordo=True)


def rescindir_consentimento(id_usuario, clausulas_ou_ids):
    """Atalho para registrar revogação (acordo=False)."""
    return registrar_consentimento(id_usuario, clausulas_ou_ids, acordo=False)


def obter_consentimentos_usuario(id_usuario):
    """Retorna o estado atual de consentimento do usuário para o termo em vigor.

    Retorna uma lista de dicionários contendo a instância da Clausula e o
    estado atual (True = aceito, False = negado, None = nunca respondeu).
    """
    termo_atual = obter_termo_atual()
    clausulas = termo_atual.clausulas.all().order_by('id_clausula')

    # Subquery para pegar o último consentimento de cada cláusula
    ultimos_consentimentos = Consentimento.objects.filter(
        id_usuario=id_usuario,
        id_clausula=OuterRef('pk')
    ).order_by('-timestamp_consentimento', '-id_consentimento')

    # Busca todas as cláusulas do termo atual e anota o valor do último acordo
    clausulas_com_status = clausulas.annotate(
        ultimo_acordo=Subquery(ultimos_consentimentos.values('acordo')[:1])
    )

    return [
        {
            'clausula': clausula,
            'requisito': clausula.requisito,
            'acordo': clausula.ultimo_acordo,
        }
        for clausula in clausulas_com_status
    ]


def obter_historico_consentimentos_usuario(id_usuario):
    """Retorna eventos de consentimento com os termos associados a cada período.

    O período de cada evento termina na próxima decisão do mesmo usuário para
    a mesma cláusula. Como o consentimento não referencia diretamente um Termo,
    as versões são inferidas pelos timestamps de criação dos termos.
    """
    if not id_usuario:
        raise ValueError('O ID do usuário é obrigatório.')

    eventos = list(
        Consentimento.objects.filter(id_usuario=id_usuario)
        .select_related('id_clausula')
        .order_by('timestamp_consentimento', 'id_consentimento')
    )
    if not eventos:
        return []

    termos = list(
        Termo.objects.prefetch_related('clausulas')
        .order_by('data_criacao', 'id_termo')
    )
    timestamps_termos = [termo.data_criacao for termo in termos]
    clausulas_por_termo = {
        termo.id_termo: {
            clausula.id_clausula for clausula in termo.clausulas.all()
        }
        for termo in termos
    }

    eventos_por_clausula = defaultdict(list)
    for evento in eventos:
        eventos_por_clausula[evento.id_clausula_id].append(evento)

    proximo_evento = {}
    for eventos_clausula in eventos_por_clausula.values():
        for indice, evento in enumerate(eventos_clausula):
            proximo_evento[evento.id_consentimento] = (
                eventos_clausula[indice + 1]
                if indice + 1 < len(eventos_clausula)
                else None
            )

    historico = []
    for evento in eventos:
        proximo = proximo_evento[evento.id_consentimento]
        indice_inicio = bisect_right(
            timestamps_termos,
            evento.timestamp_consentimento,
        ) - 1
        if indice_inicio < 0:
            termos_periodo = []
        else:
            indice_fim = (
                bisect_left(timestamps_termos, proximo.timestamp_consentimento) - 1
                if proximo is not None
                else len(termos) - 1
            )
            indice_fim = max(indice_inicio, indice_fim)
            termos_periodo = [
                termo
                for termo in termos[indice_inicio:indice_fim + 1]
                if evento.id_clausula_id in clausulas_por_termo[termo.id_termo]
            ]

        historico.append(
            {
                'consentimento': evento,
                'fim_periodo': (
                    proximo.timestamp_consentimento if proximo is not None else None
                ),
                'termos': termos_periodo,
            }
        )

    return historico


def verificar_consentimento(id_usuario, requisito):
    """Valida se o usuário consentiu com uma cláusula específica (pelo requisito).

    Retorna True se o último registro para essa cláusula for de aceite,
    e False caso contrário (ou se ele nunca respondeu).
    """
    if not id_usuario or not requisito:
        return False

    # 1. Encontra a cláusula no termo atual
    termo_atual = obter_termo_atual()
    clausula = termo_atual.clausulas.filter(requisito=requisito).first()
    if not clausula:
        return False

    # 2. Busca o último registro de consentimento para essa cláusula
    ultimo = Consentimento.objects.filter(
        id_usuario=id_usuario,
        id_clausula=clausula
    ).order_by('-timestamp_consentimento', '-id_consentimento').first()

    return ultimo.acordo if ultimo else False


class ConsentimentoService:
    """Fachada orientada a objetos para a API interna de Consentimento."""

    consentir_clausulas = staticmethod(consentir_clausulas)
    rescindir_consentimento = staticmethod(rescindir_consentimento)
    obter_consentimentos_usuario = staticmethod(obter_consentimentos_usuario)
    obter_historico_consentimentos_usuario = staticmethod(
        obter_historico_consentimentos_usuario
    )
    verificar_consentimento = staticmethod(verificar_consentimento)