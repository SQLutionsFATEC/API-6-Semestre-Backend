from rest_framework import serializers
from api.serializers.etiqueta_serializer import EtiquetaSerializer
from api.models import Documento
from api.validators.documento_validator import (
    TIPOS_ARQUIVO_PERMITIDOS,
    validar_arquivo_documento,
    validar_tipo_arquivo,
)
from api.services.authorization_service import verificar_acesso


class DocumentoSerializer(serializers.ModelSerializer):
    tipo_arquivo = serializers.CharField(required=False)
    setor = serializers.CharField(required=False, allow_blank=True)
    etiquetas = serializers.ListField(
        child=serializers.CharField(trim_whitespace=True),
        required=False,
        write_only=True,
    )
    acesso_permitido = serializers.SerializerMethodField()

    class Meta:
        model = Documento
        fields = (
            'id_documento',
            'tipo_arquivo',
            'nome',
            'setor',
            'data_criacao',
            'data_atualizacao',
            'nivel',
            'data',
            'etiquetas',
            'acesso_permitido',
        )
        read_only_fields = ('data_criacao', 'data_atualizacao')

    def create(self, validated_data):
        validated_data.pop('etiquetas', None)
        return super().create(validated_data)

    def validate(self, attrs):
        attrs = super().validate(attrs)

        for campo in ('nome', 'nivel'):
            valor = attrs.get(campo)
            if not self.partial and (not isinstance(valor, str) or not valor.strip()):
                raise serializers.ValidationError({campo: 'Este campo é obrigatório.'})

        if 'setor' in attrs and isinstance(attrs['setor'], str):
            attrs['setor'] = attrs['setor'].strip()

        arquivo = attrs.get('data')
        if arquivo:
            extensao = arquivo.name.rsplit('.', 1)[-1].lower()
            tipo_inferido = TIPOS_ARQUIVO_PERMITIDOS[f'.{extensao}']
            tipo_informado = attrs.get('tipo_arquivo')
            if tipo_informado and tipo_informado.lower() != tipo_inferido:
                raise serializers.ValidationError({
                    'tipo_arquivo': 'O tipo informado deve corresponder à extensão do arquivo.'
                })
            attrs['tipo_arquivo'] = tipo_inferido

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

    def get_acesso_permitido(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return verificar_acesso(None, None, obj.setor, obj.nivel)

        setor_usuario = getattr(request.user, 'setor', None)
        nivel_usuario = getattr(request.user, 'nivel', None)

        return verificar_acesso(setor_usuario, nivel_usuario, obj.setor, obj.nivel)

    def validate_data(self, value):
        return validar_arquivo_documento(value)

    def validate_tipo_arquivo(self, value):
        return validar_tipo_arquivo(value)


class DocumentoUpdateSerializer(serializers.ModelSerializer):
    etiquetas = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Documento.etiquetas.field.remote_field.model.objects.all(),
        required=False,
    )

    class Meta:
        model = Documento
        fields = (
            'tipo_arquivo',
            'nome',
            'setor',
            'nivel',
            'data_atualizacao',
            'data',
            'etiquetas',
        )
        extra_kwargs = {
            'data_atualizacao': {'read_only': True},
            'data': {'read_only': True},
        }

    def validate(self, attrs):
        protected_fields = {'data', 'data_atualizacao'}
        submitted_protected_fields = protected_fields.intersection(self.initial_data)
        if submitted_protected_fields:
            field = next(iter(submitted_protected_fields))
            raise serializers.ValidationError(
                {field: 'Este campo não pode ser editado.'}
            )

        return attrs

    def validate_setor(self, value):
        setores_validos = {'tecnico', 'normativo', 'juridico', 'qualitativo'}
        if value not in setores_validos:
            raise serializers.ValidationError(
                'Setor inválido. Use: tecnico, normativo, juridico ou qualitativo.'
            )
        return value

    def validate_nivel(self, value):
        niveis_validos = {'basico', 'comercial', 'militar', 'operador'}
        if value not in niveis_validos:
            raise serializers.ValidationError(
                'Nível inválido. Use: basico, comercial, militar ou operador.'
            )
        return value

    def update(self, instance, validated_data):
        etiquetas = validated_data.pop('etiquetas', serializers.empty)
        instance = super().update(instance, validated_data)

        if etiquetas is not serializers.empty:
            instance.etiquetas.set(etiquetas)

        return instance
