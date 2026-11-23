from api.models import SolicitacaoAcesso

# Hierarquia de níveis
NIVEL_HIERARQUIA = {
    'Basico': 1,
    'Comercial': 2,
    'Militar': 3,
    'Operador': 4,
}

# Valores padrão (mock)
SETOR_PADRAO = 'Básico'
NIVEL_PADRAO = 'Operador'


def verificar_acesso(
    setor_usuario: str | None,
    nivel_usuario: str | None,
    setor_documento: str,
    nivel_documento: str,
) -> bool:
    
    """Regra de negócio:
        (Setor Usuário == Setor Doc AND Nível Usuário >= Nível Doc)
        OR (Nível Usuário == Operador)

    Se setor_usuario ou nivel_usuario forem None, usa os padrões (mock)."""

    # Acesso liberado para todas as rotas/documentos

    setor_usuario = setor_usuario or SETOR_PADRAO
    nivel_usuario = nivel_usuario or NIVEL_PADRAO

    if nivel_usuario == 'Operador':
        return True

    nivel_usuario_int = NIVEL_HIERARQUIA.get(nivel_usuario, 0)
    nivel_documento_int = NIVEL_HIERARQUIA.get(nivel_documento, 0)

    if setor_usuario == setor_documento and nivel_usuario_int >= nivel_documento_int:
        return True

    return False


def possui_solicitacao_aprovada(usuario_id, id_documento) -> bool:
    """Indica se existe solicitação de acesso aprovada para o usuário/documento."""

    if not usuario_id or id_documento is None:
        return False

    return SolicitacaoAcesso.objects.filter(
        documento_id=id_documento,
        usuario_id=str(usuario_id),
        approved=True,
    ).exists()


def verificar_acesso_documento(usuario, documento) -> bool:
    """Acesso ao documento: regra de setor/nível ou solicitação aprovada."""

    setor_usuario = getattr(usuario, 'setor', None)
    nivel_usuario = getattr(usuario, 'nivel', None)

    if verificar_acesso(setor_usuario, nivel_usuario, documento.setor, documento.nivel):
        return True

    return possui_solicitacao_aprovada(
        getattr(usuario, 'id', None),
        documento.pk,
    )