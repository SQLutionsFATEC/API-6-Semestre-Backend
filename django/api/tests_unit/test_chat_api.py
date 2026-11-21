from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from api.authentication.keycloak import KeycloakUser
from api.models import Documento, DocumentoChunk, SolicitacaoAcesso
from api.services.chat_service import ChatService


pytestmark = pytest.mark.django_db


CLAIMS_BASICO_TECNICO = {
    'sub': 'user-basico-tecnico',
    'preferred_username': 'joao',
    'setor': 'Tecnico',
    'realm_access': {'roles': ['basico']},
}

CLAIMS_MILITAR_JURIDICO = {
    'sub': 'user-militar-juridico',
    'preferred_username': 'carla',
    'setor': 'Juridico',
    'realm_access': {'roles': ['militar']},
}

CLAIMS_OPERADOR = {
    'sub': 'user-operador',
    'preferred_username': 'operador',
    'setor': 'Tecnico',
    'realm_access': {'roles': ['operador']},
}


def _cliente(usuario=None):
    client = APIClient()
    if usuario is not None:
        client.force_authenticate(user=usuario)
    return client


def _criar_documento_com_chunk(nome, setor, nivel, conteudo, embedding=None):
    doc = Documento.objects.create(
        tipo_arquivo='pdf',
        nome=nome,
        setor=setor,
        nivel=nivel,
        data=f'documentos/{nome}',
    )
    DocumentoChunk.objects.create(
        id_documento=doc,
        pagina=1,
        conteudo=conteudo,
        embedding=embedding or [0.1] * 256,
    )
    return doc


def test_chat_sem_autenticacao_retorna_401():
    resposta = _cliente().post(
        '/api/chat',
        {'context': ['mensagem 1', 'resposta do sistema', 'resposta do usuario']},
        format='json',
    )

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED


def test_chat_apenas_metodo_post_permitido():
    usuario = KeycloakUser(CLAIMS_BASICO_TECNICO)
    cliente = _cliente(usuario)

    assert cliente.get('/api/chat').status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert cliente.put('/api/chat', {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert cliente.patch('/api/chat', {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert cliente.delete('/api/chat').status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_chat_payload_invalido_retorna_400():
    usuario = KeycloakUser(CLAIMS_BASICO_TECNICO)
    cliente = _cliente(usuario)

    resposta_vazia = cliente.post('/api/chat', {'context': []}, format='json')
    resposta_sem_context = cliente.post('/api/chat', {}, format='json')
    resposta_msg_vazia = cliente.post('/api/chat', {'context': ['   ']}, format='json')

    assert resposta_vazia.status_code == status.HTTP_400_BAD_REQUEST
    assert resposta_sem_context.status_code == status.HTTP_400_BAD_REQUEST
    assert resposta_msg_vazia.status_code == status.HTTP_400_BAD_REQUEST


def test_chat_extrai_substantivos_com_spacy():
    with patch(
        'api.services.chat_service.TaggingService.nlp_texto',
        return_value='safety specification system',
    ) as mock_nlp_texto:
        termo = ChatService.extrair_substantivos_mensagem(
            'What is the safety specification for the system?'
        )

    assert termo == 'safety specification system'
    mock_nlp_texto.assert_called_once_with('what is the safety specification for the system?')


def test_chat_filtra_apenas_documentos_que_usuario_tem_acesso():
    usuario = KeycloakUser(CLAIMS_BASICO_TECNICO)

    doc_permitido = _criar_documento_com_chunk(
        nome='Doc_Tecnico_Basico.pdf',
        setor='Tecnico',
        nivel='Basico',
        conteudo='Specification of the radar system maintenance.',
    )
    doc_nivel_superior = _criar_documento_com_chunk(
        nome='Doc_Tecnico_Militar.pdf',
        setor='Tecnico',
        nivel='Militar',
        conteudo='Classified military radar specification.',
    )
    doc_outro_setor = _criar_documento_com_chunk(
        nome='Doc_Juridico_Basico.pdf',
        setor='Juridico',
        nivel='Basico',
        conteudo='Legal radar contract specification.',
    )
    doc_acesso_especial = _criar_documento_com_chunk(
        nome='Doc_Juridico_Aprovado.pdf',
        setor='Juridico',
        nivel='Militar',
        conteudo='Special approved radar specification document.',
    )

    # Concede acesso especial aprovado apenas ao doc_acesso_especial
    SolicitacaoAcesso.objects.create(
        documento=doc_acesso_especial,
        usuario_id=usuario.id,
        approved=True,
    )
    # Solicitação não aprovada para doc_nivel_superior não deve conceder acesso
    SolicitacaoAcesso.objects.create(
        documento=doc_nivel_superior,
        usuario_id=usuario.id,
        approved=False,
    )

    with patch.object(
        ChatService,
        'extrair_substantivos_mensagem',
        return_value='radar',
    ), patch(
        'api.services.vector_service.VectorService.gerar_embedding',
        return_value=[0.1] * 256,
    ):
        docs_encontrados = ChatService.buscar_documentos_relevantes(
            mensagem_usuario='Tell me about radar specification',
            usuario=usuario,
            limite_documentos=3,
        )

    ids_retornados = {d['id_documento'] for d in docs_encontrados}
    assert doc_permitido.id_documento in ids_retornados
    assert doc_acesso_especial.id_documento in ids_retornados
    assert doc_nivel_superior.id_documento not in ids_retornados
    assert doc_outro_setor.id_documento not in ids_retornados


def test_chat_limita_aos_tres_documentos_mais_relevantes_no_rag():
    usuario = KeycloakUser(CLAIMS_OPERADOR)

    for i in range(1, 6):
        _criar_documento_com_chunk(
            nome=f'Manual_{i}.pdf',
            setor='Tecnico',
            nivel='Basico',
            conteudo=f'Engine maintenance procedure part {i}.',
        )

    with patch.object(
        ChatService,
        'extrair_substantivos_mensagem',
        return_value='engine',
    ), patch(
        'api.services.vector_service.VectorService.gerar_embedding',
        return_value=[0.1] * 256,
    ), patch(
        'api.services.chat_service.CHAT_HTTP_SESSION.post'
    ) as mock_post:
        mock_post.return_value.json.return_value = {
            'choices': [
                {'message': {'content': 'Resposta gerada via RAG com 3 documentos.'}}
            ]
        }
        mock_post.return_value.raise_for_status.return_value = None

        resposta = _cliente(usuario).post(
            '/api/chat',
            {
                'context': [
                    'mensagem 1',
                    'resposta do sistema',
                    'How does the engine maintenance procedure work?',
                ]
            },
            format='json',
        )

    assert resposta.status_code == status.HTTP_200_OK
    dados = resposta.json()
    assert dados['response'] == 'Resposta gerada via RAG com 3 documentos.'
    assert len(dados['documents']) == 3

    # Verifica que a requisição ao LLM foi chamada sem timeout curto (timeout=None por padrão)
    _, kwargs_chamada = mock_post.call_args
    assert kwargs_chamada.get('timeout') is None


def test_chat_fallback_quando_llm_indisponivel():
    usuario = KeycloakUser(CLAIMS_BASICO_TECNICO)
    _criar_documento_com_chunk(
        nome='Norma_Seguranca.pdf',
        setor='Tecnico',
        nivel='Basico',
        conteudo='Procedimento de segurança e proteção operacional.',
    )

    with patch.object(
        ChatService,
        'extrair_substantivos_mensagem',
        return_value='segurança',
    ), patch(
        'api.services.vector_service.VectorService.gerar_embedding',
        side_effect=RuntimeError('llama.cpp offline'),
    ), patch(
        'api.services.chat_service.CHAT_HTTP_SESSION.post',
        side_effect=RuntimeError('llama.cpp chat offline'),
    ):
        resposta = _cliente(usuario).post(
            '/api/chat',
            {'context': ['Qual o procedimento de segurança?']},
            format='json',
        )

    assert resposta.status_code == status.HTTP_200_OK
    dados = resposta.json()
    assert 'Norma_Seguranca.pdf' in dados['response']
    assert len(dados['documents']) == 1
