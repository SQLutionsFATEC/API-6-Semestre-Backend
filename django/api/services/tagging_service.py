import logging
import importlib
import spacy
import joblib
import numpy as np
import sys
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)


def _load_topic_model():
    legacy_normalize = "sentence_transformers.base.modules.normalize"
    current_normalize = "sentence_transformers.sentence_transformer.modules.normalize"
    if legacy_normalize not in sys.modules:
        sys.modules[legacy_normalize] = importlib.import_module(current_normalize)
    return joblib.load(settings.TAGGING_MODEL_PATH)


PALAVRAS_LIXO = {
    "everyspec", "downloaded", "www", "com", "https", "http", "from",
    "shall", "verify", "version", "did", "associated", "use", "current",
    "check", "applicable", "dated", "yes", "information", "operations"
}


class TaggingService:
    _model = None
    _nlp = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            cls._model = _load_topic_model()  # joblib.load(settings.TAGGING_MODEL_PATH)

    @classmethod
    def get_nlp(cls):
        if cls._nlp is None:
            cls._nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])

    @classmethod
    def nlp_texto(cls, texto):
        nlp_start = time.time()
        if not texto:
            return ""

        substantivos = []
        TAMANHO_CHUNK = settings.NLP_CHUNK_SIZE

        logger.info("nlp...")
        for i in range(0, len(texto), TAMANHO_CHUNK):
            print(i, len(texto))
            chunk = texto[i : i + TAMANHO_CHUNK]
            doc = cls._nlp(chunk)
            for token in doc:
                if token.pos_ == "NOUN" and len(token.text) >= 3 and token.is_alpha and token.lemma_ not in PALAVRAS_LIXO:
                    substantivos.append(token.lemma_)
            del doc, chunk

        logger.info(f"NLP feito em {round(time.time()-nlp_start, 2)} segundos")
        return " ".join(substantivos)

    @classmethod
    def classificar_pdf(cls, texto_limpo):
        t = time.time()
        if cls._nlp is None:
            cls.get_nlp()
        if cls._model is None:
            cls.get_model()
        substantivos = cls.nlp_texto(texto_limpo)
        etiquetas = []

        if not texto_limpo:
            logger.error("Erro: Nenhum texto útil encontrado no PDF.")
            return []

        distribuicoes, _ = cls._model.approximate_distribution(
            [texto_limpo],
            window=50,
            stride=15
        )

        notas_topicos = distribuicoes[0]
        
        # Ordena do maior pro menor
        topicos_ranqueados = np.argsort(notas_topicos)[::-1]

        for num_topico in topicos_ranqueados:
            probabilidade = notas_topicos[num_topico]
            
            # Ignora o tópico lixo (-1) e travas de segurança de 1%
            if num_topico == -1 or probabilidade < 0.01:
                continue
                
            info_topico = cls._model.get_topic_info(num_topico)
            
            if 'CustomName' in info_topico.columns:
                nome_oficial = info_topico['CustomName'].values[0]
            else:
                nome_oficial = info_topico['Name'].values[0]
                
            etiquetas.append(nome_oficial)

        if len(etiquetas) == 0:
            logger.warning("Nenhuma etiqueta atingiu a confiança mínima de 1%.")

        return etiquetas
