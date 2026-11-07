"""Serviço de gerenciamento e versionamento de Termos de Consentimento e Cláusulas.

Os termos de consentimento e suas cláusulas são imutáveis:
  - o termo em vigor é sempre o de maior ``id_termo``;
  - adicionar uma ou mais cláusulas cria as novas cláusulas e gera uma única
    nova versão de ``Termo`` mantendo as cláusulas anteriores;
  - remover uma ou mais cláusulas gera uma única nova versão de ``Termo`` sem
    as cláusulas removidas, preservando os registros antigos no banco;
  - atualizar uma cláusula cria um novo registro de ``Clausula`` e uma nova
    versão de ``Termo`` apontando para a nova cláusula e mantendo as demais.
"""

from django.db import transaction

from api.models import Clausula, Termo

REQUISITO_COLETA_NOME = 'coleta_nome'
REQUISITO_COLETA_USO_EMAIL = 'coleta_uso_email'

CLAUSULAS_INICIAIS = (
    {
        'requisito': REQUISITO_COLETA_NOME,
        'desc': 'Coleta de nome',
        'obrigatoria': True,
    },
    {
        'requisito': REQUISITO_COLETA_USO_EMAIL,
        'desc': 'Coleta e uso do email',
        'obrigatoria': False,
    },
)


def _extrair_id_clausula(clausula_ou_id):
    """Extrai o id inteiro a partir de uma instância de Clausula ou inteiro."""
    if isinstance(clausula_ou_id, Clausula):
        return clausula_ou_id.id_clausula
    if isinstance(clausula_ou_id, bool) or not isinstance(clausula_ou_id, int):
        try:
            return int(clausula_ou_id)
        except (TypeError, ValueError) as erro:
            raise ValueError('Identificador de cláusula inválido.') from erro
    return clausula_ou_id


@transaction.atomic
def garantir_termo_inicial():
    """Garante a existência do termo preliminar com duas cláusulas caso não exista nenhum termo.

    Preliminarmente, cria um Termo com:
      - uma cláusula obrigatória para coleta de nome;
      - uma cláusula opcional para coleta e uso do email.
    """
    termo_existente = (
        Termo.objects.prefetch_related('clausulas').order_by('-id_termo').first()
    )
    if termo_existente is not None:
        return termo_existente

    termo = Termo.objects.create()
    clausulas_criadas = [
        Clausula.objects.create(
            requisito=item['requisito'],
            desc=item['desc'],
            obrigatoria=item['obrigatoria'],
        )
        for item in CLAUSULAS_INICIAIS
    ]
    termo.clausulas.set(clausulas_criadas)
    return Termo.objects.prefetch_related('clausulas').get(pk=termo.pk)


def obter_termo_atual():
    """Retorna o Termo atual (de maior id_termo) com suas cláusulas.

    Caso ainda não exista nenhum termo no banco, inicializa o termo preliminar.
    """
    termo = (
        Termo.objects.prefetch_related('clausulas').order_by('-id_termo').first()
    )
    if termo is None:
        return garantir_termo_inicial()
    return termo


def listar_clausulas_atuais():
    """Retorna a lista de cláusulas pertencentes ao termo atual ordenadas por id_clausula."""
    termo = obter_termo_atual()
    return list(termo.clausulas.all().order_by('id_clausula'))


@transaction.atomic
def criar_clausulas(clausulas):
    """Cria uma ou mais cláusulas e gera uma única nova versão do Termo.

     ``clausulas`` pode ser um dicionário único ou uma lista/iterável de
    dicionários contendo ``requisito``, ``desc`` e opcionalmente ``obrigatoria``.
    """
    if isinstance(clausulas, dict):
        lista_clausulas = [clausulas]
    elif isinstance(clausulas, (list, tuple)):
        lista_clausulas = list(clausulas)
    else:
        raise ValueError('Informe um dicionário ou uma lista de cláusulas.')

    if not lista_clausulas:
        raise ValueError('Informe ao menos uma cláusula para criação.')

    dados_validados = []
    for item in lista_clausulas:
        if not isinstance(item, dict):
            raise ValueError('Cada cláusula deve ser informada como um dicionário.')
        requisito = (item.get('requisito') or '').strip()
        desc = (item.get('desc') or '').strip()
        if not requisito or not desc:
            raise ValueError('Os campos "requisito" e "desc" são obrigatórios.')
        obrigatoria = bool(item.get('obrigatoria', False))
        dados_validados.append(
            {
                'requisito': requisito,
                'desc': desc,
                'obrigatoria': obrigatoria,
            }
        )

    termo_atual = obter_termo_atual()
    clausulas_atuais = list(termo_atual.clausulas.all().order_by('id_clausula'))

    novas_clausulas = [
        Clausula.objects.create(
            requisito=dados['requisito'],
            desc=dados['desc'],
            obrigatoria=dados['obrigatoria'],
        )
        for dados in dados_validados
    ]

    novo_termo = Termo.objects.create()
    novo_termo.clausulas.set(clausulas_atuais + novas_clausulas)
    return Termo.objects.prefetch_related('clausulas').get(pk=novo_termo.pk)


def criar_clausula(requisito, desc, obrigatoria=False):
    """Atalho para criar uma única cláusula gerando uma nova versão do Termo."""
    return criar_clausulas(
        {
            'requisito': requisito,
            'desc': desc,
            'obrigatoria': obrigatoria,
        }
    )


@transaction.atomic
def remover_clausulas(clausulas_ou_ids):
    """Remove uma ou mais cláusulas do termo atual, gerando uma única nova versão do Termo.

    Os registros antigos de ``Clausula`` e ``Termo`` NÃO são deletados do banco
    de dados para preservar o histórico de versionamento.
    """
    if isinstance(clausulas_ou_ids, (int, Clausula)) and not isinstance(clausulas_ou_ids, bool):
        itens = [clausulas_ou_ids]
    elif isinstance(clausulas_ou_ids, (list, tuple, set)):
        itens = list(clausulas_ou_ids)
    else:
        raise ValueError('Informe um ID/Cláusula ou uma coleção de IDs/Cláusulas.')

    if not itens:
        raise ValueError('Informe ao menos uma cláusula para remoção.')

    ids_para_remover = {_extrair_id_clausula(item) for item in itens}

    termo_atual = obter_termo_atual()
    clausulas_atuais = list(termo_atual.clausulas.all().order_by('id_clausula'))
    ids_atuais = {c.id_clausula for c in clausulas_atuais}

    ids_inexistentes = ids_para_remover - ids_atuais
    if ids_inexistentes:
        raise ValueError(
            f'Cláusula(s) não encontrada(s) no termo atual: {sorted(ids_inexistentes)}'
        )

    clausulas_restantes = [
        c for c in clausulas_atuais if c.id_clausula not in ids_para_remover
    ]

    novo_termo = Termo.objects.create()
    novo_termo.clausulas.set(clausulas_restantes)
    return Termo.objects.prefetch_related('clausulas').get(pk=novo_termo.pk)


def remover_clausula(clausula_ou_id):
    """Atalho para remover uma única cláusula do termo atual."""
    return remover_clausulas([clausula_ou_id])


@transaction.atomic
def atualizar_clausula(clausula_ou_id, requisito=None, desc=None, obrigatoria=None):
    """Atualiza uma cláusula criando um novo registro de Clausula e um novo Termo.

    A cláusula original não é editada nem removida do banco de dados, mantendo
    íntegro o histórico dos termos anteriores.
    """
    id_alvo = _extrair_id_clausula(clausula_ou_id)

    termo_atual = obter_termo_atual()
    clausulas_atuais = list(termo_atual.clausulas.all().order_by('id_clausula'))

    clausula_antiga = next(
        (c for c in clausulas_atuais if c.id_clausula == id_alvo),
        None,
    )
    if clausula_antiga is None:
        raise ValueError(f'A cláusula {id_alvo} não pertence ao termo atual.')

    novo_requisito = (
        requisito.strip() if requisito is not None else clausula_antiga.requisito
    )
    nova_desc = desc.strip() if desc is not None else clausula_antiga.desc
    nova_obrigatoria = (
        bool(obrigatoria) if obrigatoria is not None else clausula_antiga.obrigatoria
    )

    if not novo_requisito or not nova_desc:
        raise ValueError('Os campos "requisito" e "desc" não podem ser vazios.')

    nova_clausula = Clausula.objects.create(
        requisito=novo_requisito,
        desc=nova_desc,
        obrigatoria=nova_obrigatoria,
    )

    novas_clausulas_termo = [
        nova_clausula if c.id_clausula == id_alvo else c
        for c in clausulas_atuais
    ]

    novo_termo = Termo.objects.create()
    novo_termo.clausulas.set(novas_clausulas_termo)
    return Termo.objects.prefetch_related('clausulas').get(pk=novo_termo.pk)


class TermoConsentimentoService:
    """Fachada orientada a objetos para a API interna de Termos de Consentimento."""

    garantir_termo_inicial = staticmethod(garantir_termo_inicial)
    obter_termo_atual = staticmethod(obter_termo_atual)
    listar_clausulas_atuais = staticmethod(listar_clausulas_atuais)
    criar_clausulas = staticmethod(criar_clausulas)
    criar_clausula = staticmethod(criar_clausula)
    remover_clausulas = staticmethod(remover_clausulas)
    remover_clausula = staticmethod(remover_clausula)
    atualizar_clausula = staticmethod(atualizar_clausula)

