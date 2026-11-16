from rest_framework import serializers

from api.models import Documento, SolicitacaoAcesso


class SolicitacaoAcessoSerializer(serializers.ModelSerializer):
    documento_id = serializers.PrimaryKeyRelatedField(
        source='documento',
        queryset=Documento.objects.all(),
    )
    usuario_id = serializers.CharField(read_only=True)

    class Meta:
        model = SolicitacaoAcesso
        fields = ['id', 'documento_id', 'usuario_id', 'data_solicitacao', 'approved']
        read_only_fields = ['id', 'usuario_id', 'data_solicitacao']


class SolicitacaoAcessoCreateSerializer(serializers.Serializer):
    documento_id = serializers.PrimaryKeyRelatedField(
        queryset=Documento.objects.all(),
        source='documento',
    )


class SolicitacaoAcessoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitacaoAcesso
        fields = ['approved']
