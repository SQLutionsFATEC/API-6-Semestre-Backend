"""Serializers para os endpoints de consentimento."""
from rest_framework import serializers

from api.models import Clausula


class ClausulaConsentimentoSerializer(serializers.ModelSerializer):
    """
    Serializa uma cláusula junto com o estado atual de consentimento do usuário.

    O campo `aceita` pode ser:
      - True: o usuário consentiu (registro mais recente = acordo True)
      - False: o usuário revogou (registro mais recente = acordo False)
      - None: o usuário nunca respondeu essa cláusula
    """
    aceita = serializers.BooleanField(allow_null=True, read_only=True)
    obrigatoria = serializers.BooleanField(read_only=True)

    class Meta:
        model = Clausula
        fields = ['id_clausula', 'requisito', 'desc', 'obrigatoria', 'aceita']


class TermoConsentimentoSerializer(serializers.Serializer):
    """Serializa o termo em vigor junto com o estado de todas as suas cláusulas."""
    id_termo = serializers.IntegerField(read_only=True)
    data_criacao = serializers.DateTimeField(read_only=True)
    clausulas = ClausulaConsentimentoSerializer(many=True, read_only=True)


class ConsentimentoUpdateSerializer(serializers.Serializer):
    """
    Valida o payload do PATCH.

    Formato aceito: { "<id_clausula>": true/false, ... }

    Exemplo:
        {"1": true, "2": false, "15": true}
    """

    def to_internal_value(self, data):
        if not isinstance(data, dict) or not data:
            raise serializers.ValidationError(
                "Envie um objeto chave-valor com o ID da cláusula e o boolean."
            )

        resultado = {}
        for chave, valor in data.items():
            try:
                id_clausula = int(chave)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    f"O ID '{chave}' não é um número inteiro válido."
                )
            if not isinstance(valor, bool):
                raise serializers.ValidationError(
                    f"O valor para a cláusula {id_clausula} deve ser boolean (true/false)."
                )
            resultado[id_clausula] = valor

        return resultado