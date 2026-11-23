from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from api.services.consentimento import obter_consentimentos_usuario


class TermsNotAccepted(APIException):
    status_code = 451
    default_detail = (
        'O acesso está bloqueado até que todas as cláusulas obrigatórias '
        'dos Termos e Condições vigentes sejam aceitas.'
    )
    default_code = 'terms_not_accepted'


class AceitouClausulasObrigatorias(BasePermission):
    """Exige o aceite de todas as cláusulas obrigatórias do termo vigente."""

    def has_permission(self, request, view):
        id_usuario = getattr(request.user, 'id', None)
        consentimentos = obter_consentimentos_usuario(id_usuario)
        aceitou_todas = all(
            item['acordo'] is True
            for item in consentimentos
            if item['clausula'].obrigatoria
        )
        if not aceitou_todas:
            raise TermsNotAccepted()
        return True


class IsAdminRole(BasePermission):
    """Permite acesso somente a usuários com a realm role 'admin' do Keycloak.

    A role vem no claim realm_access do access token e é mapeada para
    request.user pelo autenticador de api.authentication.keycloak."""

    message = 'Somente usuários com a role admin podem acessar este recurso.'

    def has_permission(self, request, view):
        usuario = request.user
        tem_verificacao = getattr(usuario, 'has_role', None)
        return bool(tem_verificacao and usuario.has_role('admin'))


class IsOperador(BasePermission):
    """Permite alterações em documentos somente ao nível Operador."""

    message = 'Somente usuários com nível Operador podem alterar documentos.'

    def has_permission(self, request, view):
        usuario = request.user
        tem_role = getattr(usuario, 'has_role', None)
        if tem_role and usuario.has_role('operador'):
            return True

        nivel = getattr(usuario, 'nivel_acesso', None)
        if nivel is None:
            nivel = getattr(usuario, 'nivel', None)
        return isinstance(nivel, str) and nivel.lower() == 'operador'
    
    
class IsOperadorOrAdminRole(BasePermission):
    """Permite acesso a usuários com a realm role 'operador' ou 'admin' do Keycloak."""

    message = 'Somente usuários com a role Operador ou Admin podem acessar este recurso.'

    def has_permission(self, request, view):
        usuario = request.user
        tem_verificacao = getattr(usuario, 'has_role', None)
        if not tem_verificacao:
            return False
        return usuario.has_role('admin') or usuario.has_role('operador')
