from rest_framework import serializers
from api.models import Vazamento


class VazamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vazamento
        fields = ['id', 'timestamp']