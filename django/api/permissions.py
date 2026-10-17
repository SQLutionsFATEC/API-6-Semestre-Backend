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
