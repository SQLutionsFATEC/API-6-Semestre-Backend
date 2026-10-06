import os
import tempfile
from pathlib import Path
from django.test import TestCase
from api.services.ml_service import MLService
import pymupdf


class MLServiceTest(TestCase):
    def test_limpar_texto_remove_urls_emails_espacos_e_caracteres_especiais(self):
        texto_sujo = "   Olá, acesse https://www.everyspec.com ou envie e-mail para teste@email.com!   DOWNLOADED FROM  "
        texto_limpo = MLService.limpar_texto(texto_sujo)
        self.assertEqual(texto_limpo, "ol acesse ou envie e-mail para")

    def test_limpar_texto_retorna_vazio_para_entrada_nula_ou_vazia(self):
        self.assertEqual(MLService.limpar_texto(""), "")
        self.assertEqual(MLService.limpar_texto(None), "")

    def test_classificar_documento_arquivo_inexistente_retorna_nao_classificado(self):
        resultado = MLService.classificar_documento("caminho_inexistente_12345.pdf")
        self.assertEqual(resultado, "NAO_CLASSIFICADO")

    def test_classificar_documento_arquivo_vazio_retorna_nao_classificado(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            resultado = MLService.classificar_documento(tmp_path)
            self.assertEqual(resultado, "NAO_CLASSIFICADO")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_extrair_texto_pdf_arquivo_nao_pdf_lanca_excecao_ou_retorna_vazio(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp.write(b"Conteudo texto puro nao PDF")
            tmp_path = tmp.name
        try:
            texto_extraido = MLService.extrair_texto_pdf(tmp_path)
            self.assertEqual(texto_extraido, "")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_classificar_documento_pdf_valido_com_texto(self):
        doc = pymupdf.open()
        pagina = doc.new_page()
        # Adiciona um texto longo repetido para ultrapassar 100 caracteres
        texto_exemplo = "Especificacao tecnica de material militar contrato NAVSEA " * 10
        pagina.insert_text((50, 50), texto_exemplo)
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc.save(tmp_path)
        doc.close()

        try:
            resultado = MLService.classificar_documento(tmp_path)
            self.assertIn(resultado, ["NAO_CLASSIFICADO"] + list(MLService._carregar_modelo()["model"].classes_))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_classificar_documento_com_texto_curto_retorna_nao_classificado(self):
        doc = pymupdf.open()
        pagina = doc.new_page()
        pagina.insert_text((50, 50), "Texto curto")
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc.save(tmp_path)
        doc.close()
        try:
            resultado = MLService.classificar_documento(tmp_path)
            self.assertEqual(resultado, "NAO_CLASSIFICADO")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_classificar_documento_sem_termos_reconhecidos_retorna_nao_classificado(self):
        doc = pymupdf.open()
        pagina = doc.new_page()
        pagina.insert_text((50, 50), "zzxxyyqqwwkkjj " * 20)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc.save(tmp_path)
        doc.close()
        try:
            resultado = MLService.classificar_documento(tmp_path)
            self.assertEqual(resultado, "NAO_CLASSIFICADO")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_classificar_documento_limite_confianca_alto_retorna_nao_classificado(self):
        doc = pymupdf.open()
        pagina = doc.new_page()
        pagina.insert_text((50, 50), "Especificacao tecnica militar NAVSEA " * 10)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        doc.save(tmp_path)
        doc.close()
        try:
            resultado = MLService.classificar_documento(tmp_path, limite_confianca=9999.0)
            self.assertEqual(resultado, "NAO_CLASSIFICADO")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

