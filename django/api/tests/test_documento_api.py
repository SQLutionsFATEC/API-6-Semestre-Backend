from django.test import TestCase

from api.models import Documento, Etiqueta


class DocumentoApiTest(TestCase):
    def setUp(self):
        self.documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Manual.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/manual.pdf',
        )
        self.etiqueta = Etiqueta.objects.create(
            nome='Importante'
        )


    def test_retorna_documento_pelo_id(self):
        response = self.client.get(f'/api/documentos/{self.documento.id_documento}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'id_documento': self.documento.id_documento,
            'tipo_arquivo': 'pdf',
            'nome': 'Manual.pdf',
            'setor': 'TI',
            'data_atualizacao': self.documento.data_atualizacao.isoformat().replace('+00:00', 'Z'),
            'nivel': 'Público',
            'data': 'http://testserver/media/documentos/manual.pdf',
            'etiquetas': [],
        })

    def test_retorna_404_para_documento_inexistente(self):
        response = self.client.get('/api/documentos/999999/')

        self.assertEqual(response.status_code, 404)

    def test_retorna_404_para_id_invalido(self):
        response = self.client.get('/api/documentos/abc/')

        self.assertEqual(response.status_code, 404)

    def test_retorna_200_ao_listar_documentos(self):
        response = self.client.get('/api/documentos/')

        self.assertEqual(response.status_code, 200)

    def test_lista_documentos_filtrando_nome_sem_diferenciar_maiusculas(self):
        Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Relatório Financeiro.pdf',
            setor='Financeiro',
            nivel='Público',
            data='documentos/relatorio.pdf',
        )

        response = self.client.get('/api/documentos/?nome=relat%c3%b3rio')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['pages'], 1)
        self.assertEqual(len(response.json()['results']), 1)
        self.assertEqual(response.json()['results'][0]['nome'], 'Relatório Financeiro.pdf')

    def test_lista_documentos_pagina_com_no_maximo_dez_resultados(self):
        for index in range(10):
            Documento.objects.create(
                tipo_arquivo='pdf',
                nome=f'Documento {index}.pdf',
                setor='TI',
                nivel='Público',
                data=f'documentos/documento-{index}.pdf',
            )

        primeira_pagina = self.client.get('/api/documentos/?page=1').json()
        segunda_pagina = self.client.get('/api/documentos/?page=2').json()

        self.assertEqual(primeira_pagina['pages'], 2)
        self.assertEqual(len(primeira_pagina['results']), 10)
        self.assertEqual(len(segunda_pagina['results']), 1)

    def test_lista_documentos_mantem_busca_com_html_como_texto(self):
        nome = '<script>alert(1)</script>'
        Documento.objects.create(
            tipo_arquivo='pdf',
            nome=nome,
            setor='TI',
            nivel='Público',
            data='documentos/script.pdf',
        )

        response = self.client.get('/api/documentos/', {'nome': '<script>'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['nome'], nome)

    def test_lista_documentos_rejeita_pagina_invalida(self):
        response = self.client.get('/api/documentos/?page=abc')

        self.assertEqual(response.status_code, 400)

    # Testes para GET /api/documentos/{id}/etiquetas/
    def test_retorna_etiquetas_do_documento_com_sucesso(self):
        self.documento.etiquetas.add(self.etiqueta)
        response = self.client.get(f'/api/documentos/{self.documento.id_documento}/etiquetas/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['etiquetas']), 1)
        self.assertEqual(response.json()['etiquetas'][0]['nome'], 'Importante')

    def test_retorna_404_ao_buscar_etiquetas_de_documento_inexistente(self):
        response = self.client.get('/api/documentos/999999/etiquetas/')
        
        self.assertEqual(response.status_code, 404)

    def test_retorna_400_ao_buscar_etiquetas_com_id_invalido(self):
        response = self.client.get('/api/documentos/abc/etiquetas/')
        
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['erro'], 'id_documento deve ser um número inteiro válido.')

    # Testes para POST /api/documentos/etiqueta/
    def test_vincula_etiqueta_ao_documento_com_sucesso(self):
        payload = {
            'id_documento': self.documento.id_documento,
            'id_etiqueta': self.etiqueta.id_etiqueta
        }
        response = self.client.post('/api/documentos/etiqueta/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], 'Etiqueta vinculada com sucesso!')
        self.assertTrue(self.documento.etiquetas.filter(id_etiqueta=self.etiqueta.id_etiqueta).exists())

    def test_retorna_400_ao_vincular_etiqueta_sem_enviar_dados(self):
        payload = {}
        response = self.client.post('/api/documentos/etiqueta/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['erro'], 'Os campos id_documento e id_etiqueta são obrigatórios.')

    def test_retorna_404_ao_vincular_com_documento_inexistente(self):
        payload = {
            'id_documento': 999999,
            'id_etiqueta': self.etiqueta.id_etiqueta
        }
        response = self.client.post('/api/documentos/etiqueta/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['erro'], 'Documento não encontrado.')

    def test_retorna_404_ao_vincular_com_etiqueta_inexistente(self):
        payload = {
            'id_documento': self.documento.id_documento,
            'id_etiqueta': 999999
        }
        response = self.client.post('/api/documentos/etiqueta/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['erro'], 'Etiqueta não encontrada.')

    def test_rejeita_upload_de_arquivo_que_nao_seja_pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        arquivo_png = SimpleUploadedFile("imagem.png", b"conteudo_fake", content_type="image/png")
        payload = {
            'tipo_arquivo': 'pdf',
            'nome': 'Imagem Teste',
            'setor': 'TI',
            'nivel': 'Público',
            'data': arquivo_png,
        }
        response = self.client.post('/api/documentos/', data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('data', response.json())

    def test_criar_documento_com_sucesso_via_post(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import pymupdf
        from unittest.mock import patch

        pdf = pymupdf.open()
        pdf.new_page()
        arquivo_pdf = SimpleUploadedFile(
            "teste.pdf",
            pdf.tobytes(),
            content_type="application/pdf",
        )
        pdf.close()
        payload = {
            'tipo_arquivo': 'pdf',
            'nome': 'Relatorio Teste.pdf',
            'setor': 'TI',
            'nivel': 'Público',
            'data': arquivo_pdf,
        }
        with patch(
            'api.views.documento_api.MLService.classificar_documento',
            return_value='NAO_CLASSIFICADO',
        ), patch(
            'api.views.documento_api.VectorService.processar_documento',
            return_value=0,
        ):
            response = self.client.post('/api/documentos/', data=payload)

        self.assertEqual(response.status_code, 201)
        self.assertIn('id_documento', response.json())
        self.assertTrue(Etiqueta.objects.filter(nome="NAO_CLASSIFICADO").exists())

    def test_criar_documento_retorna_400_quando_processamento_falha(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from unittest.mock import patch

        payload = {
            'tipo_arquivo': 'pdf',
            'nome': 'Relatorio Com Erro.pdf',
            'setor': 'TI',
            'nivel': 'Público',
            'data': SimpleUploadedFile(
                'erro.pdf',
                b'%PDF-1.4',
                content_type='application/pdf',
            ),
        }
        with patch(
            'api.views.documento_api.MLService.classificar_documento',
            return_value='NAO_CLASSIFICADO',
        ), patch(
            'api.views.documento_api.VectorService.processar_documento',
            side_effect=RuntimeError('falha no processamento'),
        ):
            response = self.client.post('/api/documentos/', data=payload)

        self.assertEqual(response.status_code, 400)
        self.assertIn('falha no processamento', response.json()['erro'])
        self.assertFalse(Documento.objects.filter(nome='Relatorio Com Erro.pdf').exists())

    def test_lista_documentos_rejeita_pagina_menor_que_um(self):
        response = self.client.get('/api/documentos/?page=0')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['erro'], 'page deve ser um número inteiro positivo.')

    def test_lista_documentos_retorna_404_para_pagina_inexistente(self):
        response = self.client.get('/api/documentos/?page=9999')
        self.assertEqual(response.status_code, 404)
        self.assertIn('detail', response.json())

    def test_pesquisa_documentos_retorna_os_cinco_trechos_mais_proximos(self):
        import json
        from unittest.mock import patch

        resultados = [{'id_chunk': indice} for indice in range(5)]
        with patch(
            'api.views.documento_api.VectorService.buscar_contexto',
            return_value=resultados,
        ) as buscar_contexto:
            response = self.client.get(
                '/api/documentos/',
                data=json.dumps({'contexto': '  Segurança de Redes  '}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'resultados': resultados})
        buscar_contexto.assert_called_once_with('segurança de redes', limite=5)

    def test_pesquisa_documentos_rejeita_contexto_vazio(self):
        import json

        response = self.client.get(
            '/api/documentos/',
            data=json.dumps({'contexto': '   '}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('contexto', response.json()['erro'])

    def test_cria_documento_chunk_com_embedding_valido(self):
        from api.models import DocumentoChunk

        documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Manual Vetor.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/manual-vetor.pdf',
        )

        chunk = DocumentoChunk.objects.create(
            id_documento=documento,
            pagina=1,
            conteudo='Conteúdo do documento para busca semântica.',
            embedding=[0.1] * 768,
        )

        self.assertEqual(chunk.id_documento, documento)
        self.assertEqual(chunk.pagina, 1)
        self.assertEqual(len(chunk.embedding), 768)

    def test_processar_documento_sem_arquivo_retorna_zero_chunks(self):
        from api.services.vector_service import VectorService

        documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Sem Arquivo.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/sem-arquivo.pdf',
        )

        total = VectorService.processar_documento(documento, caminho_pdf='caminho_inexistente.pdf')

        self.assertEqual(total, 0)

    def test_lista_documentos_filtrando_por_etiqueta(self):
        self.documento.etiquetas.add(self.etiqueta)

        response = self.client.get('/api/documentos/?etiquetas=importante')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)
        self.assertEqual(response.json()['results'][0]['nome'], 'Manual.pdf')

    def test_lista_documentos_filtrando_por_nome_ou_etiqueta(self):
        self.documento.etiquetas.add(self.etiqueta)

        Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Manual de Instruções.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/manual2.pdf',
        )

        response = self.client.get('/api/documentos/?nome=Manual&etiquetas=Importante')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 2)

    def test_lista_documentos_filtrando_por_multiplas_etiquetas(self):
        etiqueta2 = Etiqueta.objects.create(nome='Urgente')
        self.documento.etiquetas.add(self.etiqueta, etiqueta2)

        response = self.client.get('/api/documentos/?etiquetas=importante%20urgente')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)
        self.assertEqual(response.json()['results'][0]['nome'], 'Manual.pdf')
