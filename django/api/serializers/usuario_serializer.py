from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.core.validators import RegexValidator

from api.services.keycloak_admin import NIVEIS_ACESSO, SETORES

NIVEL_PADRAO = 'basico'
SETOR_PADRAO = 'tecnico'


def primeiro_valor(lista, padrao):
    """Retorna o primeiro valor de uma lista de atributos ou o padrão."""
    if isinstance(lista, (list, tuple)) and lista:
        return lista[0]
    return padrao


def nivel_do_usuario(papeis_realm):
    """Extrai o nivel_acesso (realm role de negócio) de um usuário."""
    for papel in papeis_realm or []:
        nome = papel.get('name') if isinstance(papel, dict) else papel
        if nome in NIVEIS_ACESSO:
            return nome
    return NIVEL_PADRAO


class UsuarioSerializer(serializers.Serializer):
    """Representação de leitura de um usuário do Keycloak.

    Converte a UserRepresentation da Admin API nos campos de negócio:
    nome, email, nivel_acesso (realm role) e setor (atributo do usuário)."""

    id = serializers.CharField(read_only=True)
    username = serializers.CharField(read_only=True)
    nome = serializers.SerializerMethodField()
    sobrenome = serializers.SerializerMethodField()
    email = serializers.EmailField(read_only=True)
    nivel_acesso = serializers.SerializerMethodField()
    setor = serializers.SerializerMethodField()
    habilitado = serializers.SerializerMethodField()

    def to_internal_value(self, data):
        return super().to_internal_value(data)

    @extend_schema_field(serializers.CharField)
    def get_nome(self, usuario):
        return usuario.get('firstName') or ''

    @extend_schema_field(serializers.CharField)
    def get_sobrenome(self, usuario):
        return usuario.get('lastName') or ''

    @extend_schema_field(serializers.CharField)
    def get_nivel_acesso(self, usuario):
        papeis = usuario.get('realmRoles') or usuario.get('realmMappings') or []
        return nivel_do_usuario(papeis)

    @extend_schema_field(serializers.CharField)
    def get_setor(self, usuario):
        atributos = usuario.get('attributes') or {}
        return primeiro_valor(atributos.get('setor'), SETOR_PADRAO)

    @extend_schema_field(serializers.BooleanField)
    def get_habilitado(self, usuario):
        return usuario.get('enabled', True)


class UsuarioPerfilUpdateSerializer(serializers.Serializer):
    """Atualização do próprio perfil: somente nome e email."""

    nome = serializers.CharField(
        required=False,
        max_length=255,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-ZÀ-ÿ\s]+$',
                message="O nome não deve conter caracteres que não são letras ou espaço simples."
            )
        ]
    )
    sobrenome = serializers.CharField(required=False, max_length=255)
    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        # Campos de negócio (setor, nivel_acesso, senha) são gerenciados
        # pelo admin em PATCH /api/usuarios/{id}/.
        permitidos = {'nome', 'sobrenome', 'email'}
        enviados = set(self.initial_data.keys())
        proibidos = enviados - permitidos
        if proibidos:
            raise serializers.ValidationError(
                {campo: 'Este campo não pode ser alterado no próprio perfil.'}
                for campo in sorted(proibidos)
            )
        return attrs


class UsuarioCreateSerializer(serializers.Serializer):
    """Criação de usuário (rota admin) com senha temporária obrigatória."""

    nome = serializers.CharField(max_length=255)
    sobrenome = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    senha_temporaria = serializers.CharField(
        write_only=True,
        min_length=8,
        help_text='Senha temporária; o usuário deve trocá-la no primeiro login.',
    )
    nivel_acesso = serializers.ChoiceField(
        choices=NIVEIS_ACESSO,
        required=False,
        default=NIVEL_PADRAO,
        help_text='Padrão: basico.',
    )
    setor = serializers.ChoiceField(
        choices=SETORES,
        required=False,
        default=SETOR_PADRAO,
        help_text='Padrão: tecnico.',
    )


class UsuarioUpdateSerializer(serializers.Serializer):
    """Modificação parcial de campos de um usuário (rota admin)."""

    nome = serializers.CharField(required=False, max_length=255)
    sobrenome = serializers.CharField(required=False, max_length=255)
    email = serializers.EmailField(required=False)
    setor = serializers.ChoiceField(choices=SETORES, required=False)
    nivel_acesso = serializers.ChoiceField(choices=NIVEIS_ACESSO, required=False)
    senha = serializers.CharField(
        required=False,
        write_only=True,
        min_length=8,
        help_text='Se informado, redefine a senha do usuário.',
    )
    senha_temporaria = serializers.BooleanField(
        required=False,
        default=True,
        write_only=True,
        help_text='Se a nova senha deve ser temporária (troca obrigatória no próximo login).',
    )
    habilitado = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if 'senha' in attrs and 'senha_temporaria' not in attrs:
            attrs['senha_temporaria'] = True
        return attrs