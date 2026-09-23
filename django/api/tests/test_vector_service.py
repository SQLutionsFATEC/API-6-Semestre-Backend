import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from api.models import Documento, DocumentoChunk
from api.services.vector_service import VectorService


class VectorServiceTest(TestCase):
    def setUp(self):
        self.documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Manual Vetor.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/manual-vetor.pdf',
        )

    def test_gerar_embedding_retorna_zeros_para_texto_vazio(self):
        embedding = VectorService.gerar_embedding('  ')

        self.assertEqual(len(embedding), 768)
        self.assertEqual(set(embedding), {0.0})

    def test_gerar_embedding_converte_resposta_do_ollama(self):
        with patch(
            'api.services.vector_service.ollama.embeddings',
            return_value={'embedding': [0.25] * 768},
        ):
            embedding = VectorService.gerar_embedding('texto')

        self.assertEqual(embedding, [0.25] * 768)

    def test_gerar_embedding_rejeita_dimensao_invalida(self):
        with patch(
            'api.services.vector_service.ollama.embeddings',
            return_value={'embedding': [0.25]},
        ):
            with self.assertRaisesRegex(RuntimeError, '768 dimensões'):
                VectorService.gerar_embedding('texto')

    def test_extrair_markdown_retorna_texto_e_numero_da_pagina(self):
        import pymupdf

        with tempfile.NamedTemporaryFile(suffix='.pdf') as arquivo:
            documento = pymupdf.open()
            documento.new_page()
            documento.save(arquivo.name)
            documento.close()
            with patch(
                'api.services.vector_service.pymupdf4llm.to_markdown',
                return_value=[
                    {
                        'text': 'Texto longo o suficiente para não acionar o OCR.',
                        'metadata': {'page_number': 3},
                    }
                ],
            ):
                paginas = VectorService._extrair_markdown_por_pagina(arquivo.name)

        self.assertEqual(paginas, [(3, 'Texto longo o suficiente para não acionar o OCR.')])

    def test_extrair_markdown_usa_ocr_para_texto_curto(self):
        import pymupdf

        with tempfile.NamedTemporaryFile(suffix='.pdf') as arquivo:
            documento = pymupdf.open()
            documento.new_page()
            documento.save(arquivo.name)
            documento.close()
            with patch(
                'api.services.vector_service.pymupdf4llm.to_markdown',
                return_value=[{'text': 'curto', 'metadata': {}}],
            ), patch.object(
                VectorService,
                '_extrair_texto_ocr',
                return_value='Texto obtido por OCR',
            ):
                paginas = VectorService._extrair_markdown_por_pagina(arquivo.name)

        self.assertEqual(paginas, [(1, 'Texto obtido por OCR')])

    def test_processar_documento_salva_chunks_extraidos(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as arquivo:
            with patch.object(
                VectorService,
                '_extrair_markdown_por_pagina',
                return_value=[(2, 'Conteudo da pagina')],
            ), patch.object(
                VectorService,
                'gerar_embedding',
                return_value=[0.1] * 768,
            ):
                total = VectorService.processar_documento(
                    self.documento,
                    caminho_pdf=arquivo.name,
                )

        self.assertEqual(total, 1)
        chunk = DocumentoChunk.objects.get(id_documento=self.documento)
        self.assertEqual(chunk.pagina, 2)
        self.assertIn(Path(arquivo.name).name, chunk.conteudo)

    def test_processar_documento_remove_chunks_quando_embedding_falha(self):
        DocumentoChunk.objects.create(
            id_documento=self.documento,
            pagina=1,
            conteudo='chunk antigo',
            embedding=[0.1] * 768,
        )
        with tempfile.NamedTemporaryFile(suffix='.pdf') as arquivo:
            with patch.object(
                VectorService,
                '_extrair_markdown_por_pagina',
                return_value=[(1, 'Conteudo')],
            ), patch.object(
                VectorService,
                'gerar_embedding',
                side_effect=RuntimeError('embedding indisponivel'),
            ):
                with self.assertRaises(RuntimeError):
                    VectorService.processar_documento(
                        self.documento,
                        caminho_pdf=arquivo.name,
                    )

        self.assertFalse(
            DocumentoChunk.objects.filter(id_documento=self.documento).exists()
        )

    def test_buscar_contexto_retorna_chunks_filtrados(self):
        from api.models import Etiqueta

        etiqueta = Etiqueta.objects.create(nome='Manual')
        self.documento.etiquetas.add(etiqueta)
        DocumentoChunk.objects.create(
            id_documento=self.documento,
            pagina=1,
            conteudo='conteudo filtravel',
            embedding=[0.1] * 768,
        )
        with patch.object(
            VectorService,
            'gerar_embedding',
            return_value=[0.1] * 768,
        ):
            contexto = VectorService.buscar_contexto(
                'pergunta',
                categoria='Manual',
            )

        self.assertEqual(len(contexto), 1)
        self.assertEqual(contexto[0]['conteudo'], 'conteudo filtravel')