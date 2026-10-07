# Hierarquia de níveis
NIVEL_HIERARQUIA = {
    'Basico': 1,
    'Comercial': 2,
    'Militar': 3,
    'Operador': 4,
}

# Valores padrão (mock) 
SETOR_PADRAO = 'Tecnico'
NIVEL_PADRAO = 'Basico'


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

    setor_usuario = setor_usuario or SETOR_PADRAO
    nivel_usuario = nivel_usuario or NIVEL_PADRAO

    if nivel_usuario == 'Operador':
        return True

    nivel_usuario_int = NIVEL_HIERARQUIA.get(nivel_usuario, 0)
    nivel_documento_int = NIVEL_HIERARQUIA.get(nivel_documento, 0)

    if setor_usuario == setor_documento and nivel_usuario_int >= nivel_documento_int:
        return True

    return False