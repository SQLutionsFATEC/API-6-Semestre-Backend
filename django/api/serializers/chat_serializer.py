from rest_framework import serializers


class ChatRequestSerializer(serializers.Serializer):
    context = serializers.ListField(
        child=serializers.CharField(allow_blank=False, trim_whitespace=True),
        allow_empty=False,
        help_text=(
            "Lista com o histórico de mensagens da conversa, alternando entre "
            "mensagens do usuário e respostas do sistema. O último item corresponde "
            "à mensagem atual do usuário."
        ),
    )

    def validate_context(self, value):
        if not isinstance(value, list) or len(value) == 0:
            raise serializers.ValidationError(
                'O campo context deve ser uma lista não vazia de mensagens.'
            )

        mensagens_limpas = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise serializers.ValidationError(
                    'Todas as mensagens do contexto devem ser textos não vazios.'
                )
            mensagens_limpas.append(item.strip())

        if not mensagens_limpas[-1]:
            raise serializers.ValidationError(
                'A última mensagem do usuário não pode ser vazia.'
            )

        return mensagens_limpas


class ChatDocumentoRelevanteSerializer(serializers.Serializer):
    id_documento = serializers.IntegerField(help_text="Identificador do documento.")
    nome = serializers.CharField(help_text="Nome do documento.")
    setor = serializers.CharField(help_text="Setor do documento.")
    nivel = serializers.CharField(help_text="Nível de acesso do documento.")
    pagina = serializers.IntegerField(help_text="Página principal do trecho utilizado.")
    conteudo = serializers.CharField(help_text="Trecho relevante extraído do documento.")


class ChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField(
        help_text="Resposta em linguagem natural gerada pelo método RAG."
    )
    documents = ChatDocumentoRelevanteSerializer(
        many=True,
        help_text="Lista com até os 3 documentos mais relevantes utilizados na geração (restritos ao acesso do usuário).",
    )
