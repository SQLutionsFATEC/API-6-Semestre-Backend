from rest_framework.authentication import SessionAuthentication


class SessionAuthenticationComDesafio(SessionAuthentication):

    def authenticate_header(self, request):
        # Retorna 'Session' como valor do header, sinalizando ao DRF que ele deve retornar 401 (e não 403).

        return 'Session'