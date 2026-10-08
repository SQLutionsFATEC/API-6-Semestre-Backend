from rest_framework import serializers
from api.serializers.etiqueta_serializer import EtiquetaSerializer
from api.models import Documento, Etiqueta
from api.validators.documento_validator import validar_extensao_pdf, validar_tipo_arquivo_pdf


class DocumentoSerializer(serializers.ModelSerializer):
    etiquetas = serializers.ListField(
        child=serializers.CharField(trim_whitespace=True),
        required=False,
        write_only=True,
    )

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

    def validate(self, attrs):
        attrs = super().validate(attrs)

        for campo in ('nome', 'setor', 'nivel'):
            valor = attrs.get(campo)
            if isinstance(valor, str) and not valor.strip():
                raise serializers.ValidationError({campo: 'Este campo é obrigatório.'})

        etiquetas = attrs.get('etiquetas') or []
        attrs['etiquetas'] = [
            nome.strip()
            for nome in etiquetas
            if isinstance(nome, str) and nome.strip()
        ]
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['etiquetas'] = EtiquetaSerializer(instance.etiquetas.all(), many=True).data
        return data

    def validate_data(self, value):
        return validar_extensao_pdf(value)

    def validate_tipo_arquivo(self, value):
        return validar_tipo_arquivo_pdf(value)