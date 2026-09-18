from rest_framework import serializers
from api.serializers.etiqueta_serializer import EtiquetaSerializer
from api.models import Documento
from api.validators.documento_validator import validar_extensao_pdf, validar_tipo_arquivo_pdf


class DocumentoSerializer(serializers.ModelSerializer):
    # Utilizado para listar todos os documentos cadastrados no sistema, já com suas etiquetas vinculadas.
    etiquetas = EtiquetaSerializer(many=True, read_only=True)

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
        )

    def validate_data(self, value):
        return validar_extensao_pdf(value)

    def validate_tipo_arquivo(self, value):
        return validar_tipo_arquivo_pdf(value)