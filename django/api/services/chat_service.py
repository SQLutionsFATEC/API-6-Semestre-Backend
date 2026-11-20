import logging
import os
import re
import requests
from typing import Any, Dict, List

from django.db.models import Q

from api.models import Documento, DocumentoChunk, SolicitacaoAcesso
from api.services.authorization_service import verificar_acesso
from api.services.tagging_service import TaggingService
from api.services.vector_service import VectorService

logger = logging.getLogger(__name__)

STOPWORDS_PT_EN = {
    'eu', 'tu', 'ele', 'ela', 'nos', 'nós', 'vos', 'eles', 'elas', 'voce', 'você',
    'meu', 'minha', 'seu', 'sua', 'nosso', 'nossa', 'este', 'esta', 'esse', 'essa',
    'isso', 'isto', 'aquele', 'aquela', 'aquilo', 'que', 'qual', 'quais', 'quem',
    'como', 'onde', 'quando', 'porque', 'por', 'para', 'com', 'sem', 'sob', 'sobre',
    'entre', 'ate', 'até', 'desde', 'de', 'do', 'da', 'dos', 'das', 'em', 'no', 'na',
    'nos', 'nas', 'ao', 'aos', 'um', 'uma', 'uns', 'umas', 'o', 'a', 'os', 'as', 'e',
    'ou', 'mas', 'se', 'nao', 'não', 'sim', 'mais', 'menos', 'muito', 'muita', 'muitos',
    'muitas', 'pouco', 'pouca', 'todo', 'toda', 'todos', 'todas', 'outro', 'outra',
    'preciso', 'precisa', 'quero', 'quer', 'gostaria', 'pode', 'poderia', 'fale',
    'diga', 'mostre', 'busque', 'buscar', 'procurar', 'procure', 'sobre', 'documento',
    'documentos', 'arquivo', 'arquivos', 'manual', 'manuais', 'poreciso', 'favor',
    'the', 'and', 'for', 'with', 'about', 'what', 'which', 'where', 'when', 'how',
    'who', 'whom', 'whose', 'why', 'this', 'that', 'these', 'those', 'from', 'into',
    'onto', 'upon', 'need', 'want', 'tell', 'show', 'find', 'search', 'document',
    'documents', 'file', 'files', 'please', 'can', 'could', 'would', 'should',
}

LLAMA_CPP_CHAT_HOST = os.getenv(
    'LLAMA_CPP_CHAT_HOST',
    os.getenv('LLAMA_CPP_HOST', 'http://llama-cpp:8080'),
).rstrip('/')
LLAMA_CPP_CHAT_ENDPOINT = os.getenv(
    'LLAMA_CPP_CHAT_ENDPOINT',
    '/v1/chat/completions',
).strip('/')
LLAMA_CPP_CHAT_MODEL = os.getenv(
    'LLAMA_CPP_CHAT_MODEL',
    'gemma-4-E4B-it',
)
LLAMA_CPP_CHAT_TIMEOUT = os.getenv('LLAMA_CPP_CHAT_TIMEOUT')

CHAT_HTTP_SESSION = requests.Session()


class ChatService:
    """Serviço responsável pela filtragem de acesso, busca por contexto com NLP e geração RAG."""

    @staticmethod
    def extrair_substantivos_mensagem(mensagem: str) -> str:
        """
        Utiliza o spaCy para extrair os substantivos (NOUN e PROPN - nomes próprios/siglas
        como NASA, FAA, ECSS) da mensagem do usuário para otimizar a busca por contexto,
        removendo stopwords e verbos comuns.
        Caso nenhum substantivo seja extraído, utiliza a mensagem original limpa como fallback.
        """
        mensagem_limpa = (mensagem or '').strip()
        if not mensagem_limpa:
            return ''

        try:
            if TaggingService._nlp is None:
                TaggingService.get_nlp()

            doc = TaggingService._nlp(mensagem_limpa)
            substantivos = []
            vistos = set()

            for token in doc:
                lema = token.lemma_.lower().strip()
                texto_token = token.text.lower().strip()
                if (
                    token.pos_ in ('NOUN', 'PROPN')
                    and len(texto_token) >= 2
                    and (token.is_alpha or texto_token.isalnum())
                    and lema not in STOPWORDS_PT_EN
                    and texto_token not in STOPWORDS_PT_EN
                ):
                    termo = lema if len(lema) >= 2 else texto_token
                    if termo not in vistos:
                        vistos.add(termo)
                        substantivos.append(termo)

            if substantivos:
                return ' '.join(substantivos)
        except Exception as erro:
            logger.warning(
                'chat etapa=nlp_fallback erro=%s',
                erro,
            )

        # Fallback: remove pontuação e stopwords conhecidas
        palavras_fallback = [
            p for p in re.findall(r'[a-zA-ZÀ-ÿ0-9]{2,}', mensagem_limpa.lower())
            if p not in STOPWORDS_PT_EN
        ]
        if palavras_fallback:
            return ' '.join(palavras_fallback)

        return mensagem_limpa

    @staticmethod
    def _eh_chunk_sumario(texto: str) -> bool:
        """
        Identifica se um chunk aparenta ser apenas um sumário/índice (Table of Contents),
        caracterizado por sequências longas de pontos ('.....') ou tabelas de índice.
        """
        if not texto:
            return True
        pontos_longos = len(re.findall(r'\.{5,}', texto))
        if pontos_longos >= 2:
            return True
        if 'table of contents' in texto.lower() and pontos_longos >= 1:
            return True
        return False

    @classmethod
    def _pontuar_chunk_relevancia(cls, chunk: Dict[str, Any], palavras: List[str]) -> float:
        """
        Calcula uma pontuação de relevância para ordenar chunks textualmente:
        - Soma pontos para cada palavra-chave encontrada no conteúdo e no nome do documento.
        - Bônus por frequência de ocorrência das palavras-chave no parágrafo.
        - Penaliza severamente páginas de sumário/índice (linhas pontilhadas '......').
        """
        conteudo = (chunk.get('conteudo') or '').lower()
        nome_doc = (chunk.get('id_documento__nome') or '').lower()

        score = 0.0
        for p in palavras:
            if p in conteudo:
                score += 10.0
                score += min(conteudo.count(p), 5) * 1.5
            if p in nome_doc:
                score += 5.0

        if cls._eh_chunk_sumario(conteudo):
            score -= 25.0

        return score

    @staticmethod
    def usuario_possui_acesso_documento(usuario: Any, documento: Documento, ids_aprovados: set[int] | None = None) -> bool:
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
        Essa pré-filtragem garante que a busca nunca utilize documentos sem permissão.
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
        ids_permitidos = [
            doc.id_documento
            for doc in documentos
            if cls.usuario_possui_acesso_documento(usuario, doc, ids_aprovados=ids_aprovados)
        ]
        return ids_permitidos

    @classmethod
    def buscar_documentos_relevantes(
        cls,
        mensagem_usuario: str,
        usuario: Any,
        limite_documentos: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Extrai substantivos da mensagem atual com spaCy, busca por contexto apenas nos
        documentos que o usuário tem acesso e retorna os `limite_documentos` (padrão: 3)
        documentos mais relevantes com seus respectivos trechos de contexto.
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

        # Consulta chunks pertencentes EXCLUSIVAMENTE aos documentos acessíveis pelo usuário
        queryset = DocumentoChunk.objects.select_related('id_documento').filter(
            id_documento_id__in=ids_acessiveis
        )

        palavras = [p for p in termo_busca.split() if len(p) >= 2]
        q_texto = (
            Q(conteudo__icontains=termo_busca)
            | Q(id_documento__nome__icontains=termo_busca)
            | Q(id_documento__etiquetas__nome__icontains=termo_busca)
        )
        for palavra in palavras:
            q_texto |= (
                Q(conteudo__icontains=palavra)
                | Q(id_documento__nome__icontains=palavra)
                | Q(id_documento__etiquetas__nome__icontains=palavra)
            )

        chunks_ranqueados: List[Dict[str, Any]] = []
        try:
            from pgvector.django import CosineDistance

            embedding = VectorService.gerar_embedding(termo_busca, prefixo='search_query')
            distancia = CosineDistance('embedding', embedding)

            queryset_vetorial = (
                queryset.filter(embedding__isnull=False)
                .annotate(distancia=distancia)
                .filter(q_texto | Q(distancia__lt=0.72))
                .order_by('distancia')[: limite_documentos * 10]
            )
            chunks_ranqueados = list(
                queryset_vetorial.values(
                    'id_chunk',
                    'pagina',
                    'conteudo',
                    'id_documento_id',
                    'id_documento__nome',
                    'id_documento__setor',
                    'id_documento__nivel',
                )
            )
        except Exception as erro:
            logger.warning('chat etapa=busca_vetorial_fallback erro=%s', erro)

        # Complementa com busca textual nos chunks caso os chunks do banco estejam
        # com embedding=NULL (ex.: após migração de dimensão) ou a busca vetorial
        # tenha retornado menos de `limite_documentos` documentos distintos
        docs_encontrados_ids = {c['id_documento_id'] for c in chunks_ranqueados}
        if len(docs_encontrados_ids) < limite_documentos:
            chunks_textuais = list(
                queryset.filter(q_texto)
                .order_by('id_chunk')[: limite_documentos * 50]
                .values(
                    'id_chunk',
                    'pagina',
                    'conteudo',
                    'id_documento_id',
                    'id_documento__nome',
                    'id_documento__setor',
                    'id_documento__nivel',
                )
            )
            # Ordena priorizando os chunks explicativos que contêm mais palavras-chave
            # e penalizando páginas de sumário/índice (Table of Contents)
            if palavras:
                chunks_textuais.sort(
                    key=lambda c: cls._pontuar_chunk_relevancia(c, palavras),
                    reverse=True,
                )
            ids_chunks_existentes = {c['id_chunk'] for c in chunks_ranqueados}
            for chunk_txt in chunks_textuais:
                if chunk_txt['id_chunk'] not in ids_chunks_existentes:
                    chunks_ranqueados.append(chunk_txt)
                    ids_chunks_existentes.add(chunk_txt['id_chunk'])

        # Se também houver chunks vindos da busca vetorial, reordena dentro de cada documento
        # para que chunks de sumário não fiquem na frente de parágrafos explicativos
        if palavras and chunks_ranqueados:
            chunks_ranqueados.sort(
                key=lambda c: (
                    not cls._eh_chunk_sumario(c.get('conteudo') or ''),
                    cls._pontuar_chunk_relevancia(c, palavras),
                ),
                reverse=True,
            )

        # Agrupa pelos 3 documentos mais relevantes mantendo a ordem de relevância
        documentos_agrupados: Dict[int, Dict[str, Any]] = {}
        for chunk in chunks_ranqueados:
            doc_id = chunk['id_documento_id']
            if doc_id not in documentos_agrupados:
                if len(documentos_agrupados) >= limite_documentos:
                    continue
                documentos_agrupados[doc_id] = {
                    'id_documento': doc_id,
                    'nome': chunk['id_documento__nome'],
                    'setor': chunk['id_documento__setor'],
                    'nivel': chunk['id_documento__nivel'],
                    'pagina': chunk['pagina'],
                    'trechos': [chunk['conteudo']],
                }
            else:
                if len(documentos_agrupados[doc_id]['trechos']) < 3:
                    documentos_agrupados[doc_id]['trechos'].append(chunk['conteudo'])

        # Fallback para documentos acessíveis que existem na tabela Documento mas ainda
        # não possuem chunks indexados (ou foram encontrados pelo nome/etiqueta)
        if len(documentos_agrupados) < limite_documentos and palavras:
            q_doc = Q(nome__icontains=termo_busca) | Q(etiquetas__nome__icontains=termo_busca)
            for palavra in palavras:
                q_doc |= Q(nome__icontains=palavra) | Q(etiquetas__nome__icontains=palavra)

            docs_extras = (
                Documento.objects.filter(id_documento__in=ids_acessiveis)
                .filter(q_doc)
                .exclude(id_documento__in=list(documentos_agrupados.keys()))
                .distinct()[: limite_documentos - len(documentos_agrupados)]
            )
            for doc_extra in docs_extras:
                primeiro_chunk = DocumentoChunk.objects.filter(id_documento=doc_extra).first()
                conteudo_extra = (
                    primeiro_chunk.conteudo
                    if primeiro_chunk
                    else f'Documento: {doc_extra.nome} (Setor: {doc_extra.setor}, Nível: {doc_extra.nivel}).'
                )
                pagina_extra = primeiro_chunk.pagina if primeiro_chunk else 1
                documentos_agrupados[doc_extra.id_documento] = {
                    'id_documento': doc_extra.id_documento,
                    'nome': doc_extra.nome,
                    'setor': doc_extra.setor,
                    'nivel': doc_extra.nivel,
                    'pagina': pagina_extra,
                    'trechos': [conteudo_extra],
                }

        resultado = []
        for doc_info in documentos_agrupados.values():
            resultado.append({
                'id_documento': doc_info['id_documento'],
                'nome': doc_info['nome'],
                'setor': doc_info['setor'],
                'nivel': doc_info['nivel'],
                'pagina': doc_info['pagina'],
                'conteudo': '\n\n'.join(doc_info['trechos']),
            })

        return resultado[:limite_documentos]

    @staticmethod
    def _montar_historico_mensagens(context: List[str]) -> List[Dict[str, str]]:
        """
        Converte a lista de strings do campo `context` em mensagens estruturadas
        alternando entre 'user' e 'assistant':
        ['mensagem 1 (user)', 'resposta do sistema (assistant)', 'resposta do usuario (user)', ...]
        """
        mensagens: List[Dict[str, str]] = []
        for indice, texto in enumerate(context):
            papel = 'user' if indice % 2 == 0 else 'assistant'
            mensagens.append({
                'role': papel,
                'content': str(texto).strip(),
            })
        return mensagens

    @classmethod
    def gerar_resposta_rag(
        cls,
        context: List[str],
        documentos_relevantes: List[Dict[str, Any]],
    ) -> str:
        """
        Método RAG: recebe o histórico da conversa (`context`) e os três documentos
        mais relevantes à mensagem atual, gerando uma resposta em linguagem natural.
        Não possui timeout restritivo por padrão (timeout=None ou configurável) para
        evitar falhas de timeout caso a geração demore.
        """
        docs_rag = documentos_relevantes[:3]
        if docs_rag:
            blocos_contexto = []
            for idx, doc in enumerate(docs_rag, start=1):
                nome = doc.get('nome', f'Documento {doc.get("id_documento", idx)}')
                pagina = doc.get('pagina', 1)
                conteudo = doc.get('conteudo', '')
                blocos_contexto.append(
                    f'[Documento {idx}: {nome} (Página {pagina})]\n{conteudo}'
                )
            contexto_documental = '\n\n---\n\n'.join(blocos_contexto)
        else:
            contexto_documental = (
                'Nenhum documento relevante ou acessível foi encontrado para esta consulta.'
            )

        system_prompt = (
            'Você é um assistente virtual corporativo inteligente. '
            'Utilize os documentos fornecidos abaixo (método RAG) para responder à mensagem '
            'do usuário em linguagem natural, de maneira clara, precisa e em português. '
            'Baseie-se estritamente nas informações contidas nos documentos acessíveis. '
            'Caso a informação não conste nos documentos, informe educadamente.\n\n'
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
            'chat etapa=rag_inicio url=%s documentos=%d mensagens_historico=%d',
            url,
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

        # Fallback em linguagem natural caso o servidor LLM local não possua modelo de geração
        # ou retorne erro, garantindo síntese dos 3 documentos sem estourar timeout na rota.
        return cls._gerar_resposta_fallback(context[-1] if context else '', docs_rag)

    @classmethod
    def _limpar_trecho_para_exibicao(cls, trecho: str) -> str:
        """
        Remove cabeçalhos repetidos 'Documento: ...', linhas de sumário ('.......')
        e divisórias vazias de tabelas Markdown ('|---|') para gerar um texto limpo.
        """
        linhas_limpas = []
        for linha in (trecho or '').splitlines():
            linha_str = linha.strip()
            if not linha_str or linha_str.startswith('Documento:'):
                continue
            if re.search(r'\.{5,}', linha_str):
                continue
            if re.match(r'^[\|\-\s:]+$', linha_str):
                continue
            # Remove pipes de tabela das bordas mantendo o texto legível
            linha_str = re.sub(r'^\||\|$', '', linha_str).strip()
            if linha_str:
                linhas_limpas.append(linha_str)

        texto = ' '.join(linhas_limpas)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto

    @classmethod
    def _gerar_resposta_fallback(cls, pergunta: str, docs_rag: List[Dict[str, Any]]) -> str:
        if not docs_rag:
            return (
                'Não foram encontrados documentos relevantes aos quais você possui acesso '
                'para responder a essa mensagem.'
            )

        resumos = []
        for doc in docs_rag:
            nome = doc.get('nome', 'Documento')
            pagina = doc.get('pagina', 1)
            trecho = (doc.get('conteudo') or '').strip()
            texto_limpo = cls._limpar_trecho_para_exibicao(trecho)
            if not texto_limpo:
                texto_limpo = trecho
            if len(texto_limpo) > 650:
                texto_limpo = texto_limpo[:647].rstrip() + '...'
            resumos.append(f'- **{nome}** (pág. {pagina}): {texto_limpo}')

        fontes_formatadas = '\n\n'.join(resumos)
        return (
            f'Com base nos documentos mais relevantes disponíveis para o seu perfil de acesso, '
            f'foram encontradas as seguintes informações sobre a sua consulta:\n\n'
            f'{fontes_formatadas}'
        )

    @classmethod
    def processar_conversa(cls, context: List[str], usuario: Any) -> Dict[str, Any]:
        """
        Orquestra o fluxo completo do chat:
        1. Obtém a mensagem atual do usuário (última mensagem de `context`).
        2. Extrai substantivos via spaCy e busca os 3 documentos mais relevantes que o usuário tem acesso.
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
