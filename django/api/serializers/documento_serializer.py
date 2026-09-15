from rest_framework import serializers

from api.models import Documento


class DocumentoSerializer(serializers.ModelSerializer):
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
        )
