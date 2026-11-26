"""Aviso por e-mail aos usuários afetados por um incidente de vazamento.

Quando este serviço roda, o incidente já foi registrado no banco 'leaks' e a
restauração de backup já foi sinalizada: o aviso não substitui nem substitui
nenhum dos dois passos. O envio é best-effort, igual ao e-mail de comprovação
da exclusão de conta (LGPD) — uma falha ao consultar o Keycloak ou ao enviar a
mensagem é registrada no log e não desfaz o registro do incidente nem a
criação do TRIGGER_RESTORE.flag.

Quem recebe: todos os usuários do realm com e-mail cadastrado, exceto contas de
service account (infraestrutura, não pessoas) e contas já anonimizadas pela
exclusão de conta, cujo e-mail termina em ``@invalid.local``.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from api.services import keycloak_admin

logger = logging.getLogger(__name__)

SUFIXO_EMAIL_ANONIMIZADO = '@invalid.local'
PREFIXO_SERVICE_ACCOUNT = 'service-account-'
# Mesmo tamanho de página usado pelo purge de usuários deletados.
TAMANHO_PAGINA = 100

ASSUNTO = 'Aviso de vazamento de dados'

# Descrição dos dados afetados, sem detalhe técnico interno nem dado de
# terceiros: cada usuário recebe apenas o que foi exposto do próprio cadastro.
DADOS_AFETADOS = (
    'dados cadastrais (nome e e-mail)',
    'documentos',
    'etiquetas',
    'chunks e vetores derivados desses documentos',
)


def _e_service_account(usuario):
    """Indica se a conta é de infraestrutura (client credentials), não pessoa."""
    if str(usuario.get('username') or '').startswith(PREFIXO_SERVICE_ACCOUNT):
        return True
    atributos = usuario.get('attributes') or {}
    return 'serviceAccountClientId' in atributos


def _e_email_valido(email):
    local, separador, dominio = email.partition('@')
    return bool(separador and local and dominio and len(email.split()) == 1)


def listar_usuarios_do_realm():
    """Lista todos os usuários do realm, percorrendo a paginação do Keycloak."""
    usuarios = []
    inicio = 0
    while True:
        pagina = keycloak_admin.listar_usuarios(
            inicio=inicio, maximo=TAMANHO_PAGINA
        )
        if not pagina:
            return usuarios
        usuarios.extend(pagina)
        inicio += TAMANHO_PAGINA


def listar_destinatarios():
    """Retorna os e-mails de todos os usuários elegíveis ao aviso.

    Ficam de fora usuários sem e-mail, com e-mail inválido, contas de service
    account e contas anonimizadas pela exclusão de conta.
    """
    destinatarios = []
    for usuario in listar_usuarios_do_realm():
        email = str(usuario.get('email') or '').strip()
        if not email or not _e_email_valido(email):
            continue
        if email.lower().endswith(SUFIXO_EMAIL_ANONIMIZADO):
            continue
        if _e_service_account(usuario):
            continue
        destinatarios.append(email)
    return destinatarios


def _formatar_momento(vazamento):
    """Data e hora do incidente no fuso local, com segundos."""
    momento = vazamento.timestamp
    if timezone.is_naive(momento):
        momento = timezone.make_aware(momento)
    return timezone.localtime(momento).strftime('%d/%m/%Y às %H:%M:%S')


def montar_mensagem(vazamento):
    """Monta ``(assunto, corpo)`` do aviso para um incidente registrado."""
    momento = _formatar_momento(vazamento)
    suporte = getattr(settings, 'SUPORTE_EMAIL', settings.DEFAULT_FROM_EMAIL)
    itens = ''.join(f'- {dado};\n' for dado in DADOS_AFETADOS)
    mensagem = (
        'Olá,\n\n'
        f'Identificamos um incidente de vazamento de dados registrado em '
        f'{momento}.\n\n'
        'Os dados afetados são:\n'
        f'{itens}\n'
        'Recomendamos que você troque a senha da sua conta imediatamente e '
        'não reutilize essa senha em outros serviços. Se você identificar '
        'acessos que não reconhece, entre em contato com o suporte pelo '
        f'e-mail {suporte}.\n\n'
        'Atenciosamente,\nEquipe SQLutions'
    )
    return ASSUNTO, mensagem


def enviar_aviso_vazamento(vazamento):
    """Envia o aviso do incidente para cada destinatário elegível.

    Retorna quantas mensagens foram entregues ao backend de e-mail. Nunca
    levanta exceção: o incidente já está registrado e a restauração já foi
    sinalizada, então falhas (Keycloak indisponível, SMTP fora do ar, nenhum
    destinatário) apenas são registradas no log. Uma falha em um destinatário
    não interrompe o envio para os demais.
    """
    if vazamento is None:
        logger.warning('Aviso de vazamento não enviado: incidente ausente.')
        return 0

    try:
        destinatarios = listar_destinatarios()
    except Exception:
        logger.exception(
            'Falha ao listar os usuários para o aviso de vazamento.'
        )
        return 0

    if not destinatarios:
        logger.warning(
            'Aviso de vazamento sem destinatários elegíveis; nenhum e-mail '
            'enviado.'
        )
        return 0

    assunto, mensagem = montar_mensagem(vazamento)
    enviados = 0
    for email in destinatarios:
        try:
            send_mail(
                assunto,
                mensagem,
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
            enviados += 1
        except Exception:
            logger.exception(
                'Falha ao enviar o aviso de vazamento para um destinatário.'
            )

    logger.info(
        'Aviso de vazamento enviado para %s de %s destinatário(s).',
        enviados,
        len(destinatarios),
    )
    return enviados
