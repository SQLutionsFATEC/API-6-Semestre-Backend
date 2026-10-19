from rest_framework.permissions import BasePermission


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
