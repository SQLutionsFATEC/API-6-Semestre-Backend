from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema

from api.serializers.chat_serializer import (
    ChatRequestSerializer,
    ChatResponseSerializer,
)
from api.services.chat_service import ChatService


class ChatView(APIView):
    """
    Rota de conversa com o chat utilizando busca semântica filtrada por permissões
    do usuário e geração de linguagem natural via RAG.
    """

    permission_classes = [IsAuthenticated]
    http_method_names = ['post', 'options']

    @extend_schema(
        summary='Conversa com o chat via RAG',
        description=(
            'Recebe o histórico de mensagens da conversa no campo `context` '
            '(`{"context": ["mensagem 1", "resposta do sistema", "resposta do usuario"]}`). '
            'Extrai os substantivos da última mensagem do usuário utilizando spaCy (NLP), '
            'realiza a busca por contexto filtrando estritamente pelos documentos aos quais '
            'o usuário autenticado possui acesso (por setor/nível, nível Operador ou '
            'solicitação de acesso aprovada) e seleciona os três documentos mais relevantes '
            'para gerar uma resposta em linguagem natural através do método RAG. '
            'Requer autenticação Bearer; retorna 401 caso o usuário não esteja autenticado.'
        ),
        request=ChatRequestSerializer,
        examples=[
            OpenApiExample(
                'Exemplo de conversa com o chat',
                value={
                    'context': [
                        'mensagem 1',
                        'resposta do sistema',
                        'resposta do usuario',
                    ]
                },
                request_only=True,
            ),
        ],
        responses={
            200: ChatResponseSerializer,
            400: OpenApiResponse(description='Payload inválido ou lista context vazia.'),
            401: OpenApiResponse(description='Unauthenticated - Usuário não autenticado.'),
        },
    )
    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        context = serializer.validated_data['context']
        resultado = ChatService.processar_conversa(
            context=context,
            usuario=request.user,
        )

        return Response(
            ChatResponseSerializer(resultado).data,
            status=status.HTTP_200_OK,
        )
