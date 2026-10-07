from rest_framework import serializers
from api.serializers.etiqueta_serializer import EtiquetaSerializer
from api.models import Documento
from api.validators.documento_validator import validar_extensao_pdf, validar_tipo_arquivo_pdf
from api.services.authorization_service import verificar_acesso


class DocumentoSerializer(serializers.ModelSerializer):
    etiquetas = EtiquetaSerializer(many=True, read_only=True)
    acesso_permitido = serializers.SerializerMethodField()

    class Meta:
        model = Documento
        fields = (
            'id_documento',
            'tipo_arquivo',
            'nome',
            'setor',
            'data_atualizacao',
            'nivel',
            'data',
            'etiquetas',
            'acesso_permitido',
        )

    def get_acesso_permitido(self, obj):

        request = self.context.get('request')
        if not request or not request.user:

            return verificar_acesso(None, None, obj.setor, obj.nivel)

        setor_usuario = getattr(request.user, 'setor', None)
        nivel_usuario = getattr(request.user, 'nivel', None)

        return verificar_acesso(setor_usuario, nivel_usuario, obj.setor, obj.nivel)

    def validate_data(self, value):
        return validar_extensao_pdf(value)

    def validate_tipo_arquivo(self, value):
        return validar_tipo_arquivo_pdf(value)