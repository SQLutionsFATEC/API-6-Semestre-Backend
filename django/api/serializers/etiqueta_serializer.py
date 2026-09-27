from rest_framework import serializers

from api.models import Etiqueta


class EtiquetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Etiqueta
        fields = (
            'id_etiqueta',
            'nome',
        )