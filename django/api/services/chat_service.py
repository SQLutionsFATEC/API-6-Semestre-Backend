import logging
import os
import re
import requests
from typing import Any, Dict, List

from api.models import Documento, SolicitacaoAcesso
from api.services.authorization_service import verificar_acesso
from api.services.tagging_service import TaggingService

logger = logging.getLogger(__name__)

STOPWORDS_BUSCA = {
    'eu', 'tu', 'ele', 'ela', 'nos', 'nós', 'voce', 'você', 'meu', 'minha',
    'seu', 'sua', 'este', 'esta', 'esse', 'essa', 'isso', 'isto', 'que',
    'qual', 'quais', 'como', 'onde', 'quando', 'porque', 'por', 'para',
    'com', 'sem', 'sobre', 'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na',
    'um', 'uma', 'o', 'a', 'os', 'as', 'e', 'ou', 'preciso', 'poreciso',
    'quero', 'gostaria', 'documento', 'documentos', 'manual', 'manuais',
    'the', 'and', 'for', 'with', 'about', 'what', 'which', 'where', 'when',
    'how', 'this', 'that', 'from', 'need', 'want', 'document', 'documents',
}

LLAMA_CPP_CHAT_HOST = os.getenv(
    'LLAMA_CPP_CHAT_HOST',
    'http://llama-cpp-chat:8080',
).rstrip('/')
LLAMA_CPP_CHAT_ENDPOINT = os.getenv(
    'LLAMA_CPP_CHAT_ENDPOINT',
    '/v1/chat/completions',
).strip('/')
LLAMA_CPP_CHAT_MODEL = os.getenv(
    'LLAMA_CPP_CHAT_MODEL',
    os.getenv('LLAMA_CPP_CHAT_MODEL_FILE', 'qwen2.5-0.5b-instruct-q4_k_m.gguf'),
)
LLAMA_CPP_CHAT_TIMEOUT = os.getenv('LLAMA_CPP_CHAT_TIMEOUT')

CHAT_HTTP_SESSION = requests.Session()


class ChatService:
    """Serviço responsável pela filtragem de acesso, busca por contexto com NLP e geração RAG."""

    @staticmethod
    def extrair_substantivos_mensagem(mensagem: str) -> str:
        """
        Utiliza o spaCy através do TaggingService.nlp_texto já existente no projeto
        para extrair os substantivos da mensagem do usuário.
        Complementa com nomes próprios/siglas (PROPN como NASA, FAA, AC) caso presentes.
        """
        mensagem_limpa = (mensagem or '').strip()
        if not mensagem_limpa:
            return ''

        try:
            substantivos_str = TaggingService.nlp_texto(mensagem_limpa.lower())
            termos = [
                t for t in (substantivos_str or '').split()
                if t not in STOPWORDS_BUSCA
            ]
            if TaggingService._nlp is not None:
                doc = TaggingService._nlp(mensagem_limpa)
                for token in doc:
                    texto_tok = token.text.lower().strip()
                    if (
                        token.pos_ == 'PROPN'
                        and len(texto_tok) >= 2
                        and texto_tok.isalnum()
                        and texto_tok not in STOPWORDS_BUSCA
                        and texto_tok not in termos
                    ):
                        termos.append(texto_tok)
            if termos:
                return ' '.join(termos)
        except Exception as erro:
            logger.warning('chat etapa=nlp_fallback erro=%s', erro)

        palavras = [
            p for p in re.findall(r'[a-zA-ZÀ-ÿ0-9]{2,}', mensagem_limpa.lower())
            if p not in STOPWORDS_BUSCA
        ]
        if palavras:
            return ' '.join(palavras)

        return mensagem_limpa

    @staticmethod
    def usuario_possui_acesso_documento(
        usuario: Any,
        documento: Documento,
        ids_aprovados: set[int] | None = None,
    ) -> bool:
        """
        Verifica se o usuário possui acesso ao documento via regra de setor/nível
        (verificar_acesso) ou via solicitação de acesso aprovada (SolicitacaoAcesso).
        """
        setor_usuario = getattr(usuario, 'setor', None)
        nivel_usuario = getattr(usuario, 'nivel', None)

        if verificar_acesso(setor_usuario, nivel_usuario, documento.setor, documento.nivel):
            return True

        usuario_id = str(getattr(usuario, 'id', '') or '')
        if not usuario_id:
            return False

        if ids_aprovados is not None:
            return documento.id_documento in ids_aprovados

        return SolicitacaoAcesso.objects.filter(
            documento_id=documento.id_documento,
            usuario_id=usuario_id,
            approved=True,
        ).exists()

    @classmethod
    def obter_ids_documentos_acessiveis(cls, usuario: Any) -> List[int]:
        """
        Retorna a lista de IDs de todos os documentos aos quais o usuário atual possui acesso.
        """
        usuario_id = str(getattr(usuario, 'id', '') or '')
        ids_aprovados: set[int] = set()
        if usuario_id:
            ids_aprovados = set(
                SolicitacaoAcesso.objects.filter(
                    usuario_id=usuario_id,
                    approved=True,
                ).values_list('documento_id', flat=True)
            )

        documentos = Documento.objects.only('id_documento', 'setor', 'nivel')
        return [
            doc.id_documento
            for doc in documentos
            if cls.usuario_possui_acesso_documento(usuario, doc, ids_aprovados=ids_aprovados)
        ]

    @classmethod
    def buscar_documentos_relevantes(
        cls,
        mensagem_usuario: str,
        usuario: Any,
        limite_documentos: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Extrai substantivos da mensagem atual com spaCy (TaggingService.nlp_texto) e
        utiliza o mecanismo de busca por contexto da rota de documentos
        (DocumentoViewSet.filtrar_por_contexto / VectorService.buscar_contexto),
        restringindo estritamente aos documentos que o usuário possui acesso e
        retornando os 3 documentos mais relevantes.
        """
        mensagem_usuario = (mensagem_usuario or '').strip()
        if not mensagem_usuario:
            return []

        ids_acessiveis = cls.obter_ids_documentos_acessiveis(usuario)
        if not ids_acessiveis:
            logger.info('chat etapa=busca_sem_documentos_acessiveis usuario=%s', getattr(usuario, 'id', ''))
            return []

        termo_busca = cls.extrair_substantivos_mensagem(mensagem_usuario)
        logger.info(
            'chat etapa=busca_contexto mensagem_len=%d termo_busca=%s docs_acessiveis=%d',
            len(mensagem_usuario),
            termo_busca,
            len(ids_acessiveis),
        )

        from api.views.documento_api import DocumentoViewSet

        queryset_base = Documento.objects.filter(id_documento__in=ids_acessiveis)
        queryset_ordenado, chunks = DocumentoViewSet.filtrar_por_contexto(
            queryset=queryset_base,
            contexto=termo_busca,
            limite=limite_documentos * 5,
            ids_documentos_permitidos=ids_acessiveis,
        )

        if not chunks and termo_busca.lower() != mensagem_usuario.lower():
            queryset_ordenado, chunks = DocumentoViewSet.filtrar_por_contexto(
                queryset=queryset_base,
                contexto=mensagem_usuario,
                limite=limite_documentos * 5,
                ids_documentos_permitidos=ids_acessiveis,
            )

        chunks_por_doc: Dict[int, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            doc_id = chunk['id_documento_id']
            if doc_id not in chunks_por_doc:
                chunks_por_doc[doc_id] = []
            if len(chunks_por_doc[doc_id]) < 3:
                chunks_por_doc[doc_id].append(chunk)

        resultado: List[Dict[str, Any]] = []
        for doc in queryset_ordenado[:limite_documentos]:
            trechos_doc = chunks_por_doc.get(doc.id_documento, [])
            pagina_principal = trechos_doc[0]['pagina'] if trechos_doc else 1
            conteudo_combinado = '\n\n'.join(c['conteudo'] for c in trechos_doc)
            resultado.append({
                'id_documento': doc.id_documento,
                'nome': doc.nome,
                'setor': doc.setor,
                'nivel': doc.nivel,
                'pagina': pagina_principal,
                'conteudo': conteudo_combinado,
            })

        return resultado

    @staticmethod
    def _montar_historico_mensagens(context: List[str]) -> List[Dict[str, str]]:
        """
        Converte a lista de strings do campo `context` em mensagens estruturadas
        alternando entre 'user' e 'assistant'.
        """
        return [
            {
                'role': 'user' if indice % 2 == 0 else 'assistant',
                'content': str(texto).strip(),
            }
            for indice, texto in enumerate(context)
        ]

    @classmethod
    def gerar_resposta_rag(
        cls,
        context: List[str],
        documentos_relevantes: List[Dict[str, Any]],
    ) -> str:
        """
        Método RAG: recebe o histórico da conversa (`context`) e os três documentos
        mais relevantes à mensagem atual, gerando uma resposta em linguagem natural
        através do modelo carregado no serviço llama.cpp.
        """
        docs_rag = documentos_relevantes[:3]
        if docs_rag:
            blocos_contexto = [
                f'[Documento {idx}: {doc.get("nome", f"Documento {idx}")} '
                f'(Página {doc.get("pagina", 1)})]\n{doc.get("conteudo", "")}'
                for idx, doc in enumerate(docs_rag, start=1)
            ]
            contexto_documental = '\n\n---\n\n'.join(blocos_contexto)
        else:
            contexto_documental = (
                'Nenhum documento relevante ou acessível foi encontrado para esta consulta.'
            )

        system_prompt = (
            'Você é um assistente virtual corporativo. '
            'Utilize os três documentos mais relevantes fornecidos abaixo (método RAG) '
            'para responder à mensagem do usuário em linguagem natural e em português. '
            'Baseie-se apenas nos documentos fornecidos.\n\n'
            f'=== DOCUMENTOS MAIS RELEVANTES ===\n{contexto_documental}\n'
            '=================================='
        )

        historico = cls._montar_historico_mensagens(context)
        mensagens_payload = [{'role': 'system', 'content': system_prompt}] + historico

        timeout_val = (
            float(LLAMA_CPP_CHAT_TIMEOUT)
            if LLAMA_CPP_CHAT_TIMEOUT is not None and str(LLAMA_CPP_CHAT_TIMEOUT).strip() != ''
            else None
        )

        url = f'{LLAMA_CPP_CHAT_HOST}/{LLAMA_CPP_CHAT_ENDPOINT}'
        logger.info(
            'chat etapa=rag_inicio url=%s modelo=%s documentos=%d mensagens_historico=%d',
            url,
            LLAMA_CPP_CHAT_MODEL,
            len(docs_rag),
            len(historico),
        )

        try:
            resposta = CHAT_HTTP_SESSION.post(
                url,
                json={
                    'model': LLAMA_CPP_CHAT_MODEL,
                    'messages': mensagens_payload,
                    'temperature': 0.3,
                    'max_tokens': 512,
                },
                timeout=timeout_val,
            )
            resposta.raise_for_status()
            payload = resposta.json()

            choices = payload.get('choices', [])
            if choices and isinstance(choices[0], dict):
                mensagem_gerada = (
                    choices[0].get('message', {}).get('content')
                    or choices[0].get('text')
                    or ''
                ).strip()
                if mensagem_gerada:
                    return mensagem_gerada
        except Exception as erro:
            logger.warning(
                'chat etapa=rag_llm_indisponivel_fallback erro=%s',
                erro,
            )

        if not docs_rag:
            return (
                'Não foram encontrados documentos relevantes aos quais você possui acesso '
                'para responder a essa mensagem.'
            )

        fontes = ', '.join(f'{d.get("nome")} (pág. {d.get("pagina", 1)})' for d in docs_rag)
        return f'Documentos mais relevantes encontrados para sua consulta: {fontes}.'

    @classmethod
    def processar_conversa(cls, context: List[str], usuario: Any) -> Dict[str, Any]:
        """
        Orquestra o fluxo completo do chat:
        1. Obtém a mensagem atual do usuário (última mensagem de `context`).
        2. Extrai substantivos via spaCy e chama a busca por contexto filtrando pelos documentos que o usuário tem acesso.
        3. Executa o método RAG com os 3 documentos mais relevantes para gerar a resposta em linguagem natural.
        """
        mensagem_atual = context[-1].strip() if context else ''
        documentos_relevantes = cls.buscar_documentos_relevantes(
            mensagem_usuario=mensagem_atual,
            usuario=usuario,
            limite_documentos=3,
        )
        resposta_rag = cls.gerar_resposta_rag(
            context=context,
            documentos_relevantes=documentos_relevantes,
        )
        return {
            'response': resposta_rag,
            'documents': documentos_relevantes,
        }
