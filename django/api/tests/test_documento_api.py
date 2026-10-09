from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

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

        self.api_client = APIClient()
        User = get_user_model()
        user_mock = User.objects.create_user(
            username='test_user_mock',
            password='senha123',
        )
        user_mock.setor = 'TI'
        user_mock.nivel = 'Operador'  
        self.api_client.force_authenticate(user=user_mock)

        self.client = self.api_client


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
            'acesso_permitido': True, 
        })

    def test_retorna_404_para_documento_inexistente(self):
        response = self.client.get('/api/documentos/999999/')

        self.assertEqual(response.status_code, 404)

    def test_retorna_404_para_id_invalido(self):
        response = self.client.get('/api/documentos/abc/')

        self.assertEqual(response.status_code, 404)

    def test_atualiza_nome_com_patch_e_retorna_204(self):
        data_anterior = timezone.now() - timedelta(days=1)
        Documento.objects.filter(id_documento=self.documento.id_documento).update(
            data_atualizacao=data_anterior,
        )

        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'nome': 'Manual atualizado.pdf'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.nome, 'Manual atualizado.pdf')
        self.assertGreater(self.documento.data_atualizacao, data_anterior)

    def test_rejeita_atualizacao_do_arquivo(self):
        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'data': 'documentos/outro.pdf'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('data', response.json())

    def test_rejeita_atualizacao_da_data_de_atualizacao(self):
        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'data_atualizacao': '2026-01-01T00:00:00Z'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('data_atualizacao', response.json())

    def test_atualiza_setor_e_nivel_com_valores_validos(self):
        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'setor': 'normativo', 'nivel': 'militar'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 204)
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.setor, 'normativo')
        self.assertEqual(self.documento.nivel, 'militar')

    def test_rejeita_setor_e_nivel_inexistentes(self):
        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'setor': 'inexistente', 'nivel': 'inexistente'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('setor', response.json())
        self.assertIn('nivel', response.json())

    def test_substitui_lista_completa_de_etiquetas(self):
        etiqueta2 = Etiqueta.objects.create(nome='Urgente')
        etiqueta3 = Etiqueta.objects.create(nome='Revisar')
        self.documento.etiquetas.add(self.etiqueta, etiqueta2)

        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'etiquetas': [etiqueta2.id_etiqueta, etiqueta3.id_etiqueta]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            set(self.documento.etiquetas.values_list('id_etiqueta', flat=True)),
            {etiqueta2.id_etiqueta, etiqueta3.id_etiqueta},
        )

    def test_rejeita_etiqueta_inexistente(self):
        response = self.client.patch(
            f'/api/documentos/{self.documento.id_documento}/',
            data={'etiquetas': [999999]},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('etiquetas', response.json())

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
        resultados = [
            {'id_chunk': indice, 'id_documento_id': self.documento.id_documento}
            for indice in range(5)
        ]
        with patch(
            'api.views.documento_api.VectorService.buscar_contexto',
            return_value=resultados,
        ) as buscar_contexto:
            response = self.client.get(
                '/api/documentos/',
                {'contexto': '  Segurança de Redes  '},
            )

        self.assertEqual(response.status_code, 200)
        resposta = response.json()['results']
        self.assertEqual(len(resposta), 1)
        self.assertEqual(resposta[0]['id_documento'], self.documento.id_documento)
        buscar_contexto.assert_called_once_with('segurança de redes', limite=5)

    def test_pesquisa_documentos_ignora_contexto_vazio(self):
        with patch(
                'api.views.documento_api.VectorService.buscar_contexto'
        ) as buscar_contexto:
            response = self.client.get(
                '/api/documentos/',
                {'contexto': '   '},
            )

        self.assertEqual(response.status_code, 200)
        buscar_contexto.assert_not_called()

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

    def test_lista_documentos_combina_nome_e_etiqueta_com_and(self):
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
        resultados = response.json()['results']
        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]['nome'], 'Manual.pdf')

    def test_lista_documentos_filtrando_por_multiplas_etiquetas(self):
        etiqueta2 = Etiqueta.objects.create(nome='Urgente')
        self.documento.etiquetas.add(self.etiqueta, etiqueta2)
        outro_documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Documento Urgente.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/urgente.pdf',
        )
        outro_documento.etiquetas.add(etiqueta2)

        response = self.client.get('/api/documentos/?etiquetas=importante%20urgente')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 1)
        self.assertEqual(response.json()['results'][0]['nome'], 'Manual.pdf')


class DocumentoAuthorizationTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        User = get_user_model()

        # Usuário sem setor/nivel 
        self.user_sem_dados = User.objects.create_user(
            username='sem_dados', password='senha123'
        )

        # Usuário TI / Básico
        self.user_basico_ti = User.objects.create_user(
            username='basico_ti', password='senha123'
        )
        self.user_basico_ti.setor = 'TI'
        self.user_basico_ti.nivel = 'Basico'

        # Usuário TI / Comercial
        self.user_comercial_ti = User.objects.create_user(
            username='comercial_ti', password='senha123'
        )
        self.user_comercial_ti.setor = 'TI'
        self.user_comercial_ti.nivel = 'Comercial'

        # Usuário TI / Militar
        self.user_militar_ti = User.objects.create_user(
            username='militar_ti', password='senha123'
        )
        self.user_militar_ti.setor = 'TI'
        self.user_militar_ti.nivel = 'Militar'

        # Usuário RH / Operador
        self.user_operador_rh = User.objects.create_user(
            username='operador_rh', password='senha123'
        )
        self.user_operador_rh.setor = 'RH'
        self.user_operador_rh.nivel = 'Operador'

        # Documentos
        self.doc_ti_basico = Documento.objects.create(
            tipo_arquivo='pdf', nome='Doc TI Básico.pdf',
            setor='TI', nivel='Basico', data='documentos/doc1.pdf',
        )
        self.doc_ti_militar = Documento.objects.create(
            tipo_arquivo='pdf', nome='Doc TI Militar.pdf',
            setor='TI', nivel='Militar', data='documentos/doc2.pdf',
        )
        self.doc_tecnico_basico = Documento.objects.create(
            tipo_arquivo='pdf', nome='Doc Técnico Básico.pdf',
            setor='Tecnico', nivel='Basico', data='documentos/doc3.pdf',
        )

#LISTAGEM (GET /api/documentos/
    def test_listagem_sem_autenticacao_retorna_401(self):
        """Sem token/autenticação, deve retornar 401."""
        response = self.client.get('/api/documentos/')
        self.assertEqual(response.status_code, 401)

    def test_listagem_nao_filtra_por_permissao(self):
        """A lista deve conter TODOS os documentos, independente de permissão."""
        self.client.force_authenticate(user=self.user_basico_ti)
        response = self.client.get('/api/documentos/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 3)

    def test_listagem_inclui_campo_acesso_permitido(self):
        """O campo 'acesso_permitido' deve refletir a regra de negócio."""
        self.client.force_authenticate(user=self.user_basico_ti)
        response = self.client.get('/api/documentos/')

        docs = {d['nome']: d for d in response.json()['results']}

        # TI/Basico acessa TI/Basico → True
        self.assertTrue(docs['Doc TI Básico.pdf']['acesso_permitido'])
        # TI/Basico NÃO acessa TI/Militar (nível menor) → False
        self.assertFalse(docs['Doc TI Militar.pdf']['acesso_permitido'])
        # TI/Basico NÃO acessa Tecnico/Basico (setor diferente) → False
        self.assertFalse(docs['Doc Técnico Básico.pdf']['acesso_permitido'])

    def test_listagem_usuario_sem_dados_usa_mock_padrao(self):
        """Usuário sem setor/nivel → assume mock padrão: Tecnico / Basico."""
        self.client.force_authenticate(user=self.user_sem_dados)
        response = self.client.get('/api/documentos/')

        docs = {d['nome']: d for d in response.json()['results']}

        # Com o mock padrão (Tecnico/Basico), só o doc Tecnico/Basico é permitido
        self.assertTrue(docs['Doc Técnico Básico.pdf']['acesso_permitido'])
        self.assertFalse(docs['Doc TI Básico.pdf']['acesso_permitido'])

    def test_listagem_operador_tem_acesso_total(self):
        """Operador deve ter acesso_permitido=True em TODOS os documentos."""
        self.client.force_authenticate(user=self.user_operador_rh)
        response = self.client.get('/api/documentos/')

        for doc in response.json()['results']:
            self.assertTrue(doc['acesso_permitido'])

    #DETALHE (GET /api/documentos/{id}/
    def test_detalhe_sem_autenticacao_retorna_401(self):
        response = self.client.get(
            f'/api/documentos/{self.doc_ti_basico.id_documento}/'
        )
        self.assertEqual(response.status_code, 401)

    def test_detalhe_mesmo_setor_nivel_igual_retorna_200(self):
        """TI/Basico acessa TI/Basico → 200."""
        self.client.force_authenticate(user=self.user_basico_ti)
        response = self.client.get(
            f'/api/documentos/{self.doc_ti_basico.id_documento}/'
        )
        self.assertEqual(response.status_code, 200)

    def test_detalhe_mesmo_setor_nivel_maior_retorna_200(self):
        """TI/Comercial acessa TI/Basico → 200 (nível maior)."""
        self.client.force_authenticate(user=self.user_comercial_ti)
        response = self.client.get(
            f'/api/documentos/{self.doc_ti_basico.id_documento}/'
        )
        self.assertEqual(response.status_code, 200)

    def test_detalhe_mesmo_setor_nivel_menor_retorna_403(self):
        """TI/Basico tenta acessar TI/Militar → 403 (nível menor)."""
        self.client.force_authenticate(user=self.user_basico_ti)
        response = self.client.get(
            f'/api/documentos/{self.doc_ti_militar.id_documento}/'
        )
        self.assertEqual(response.status_code, 403)

    def test_detalhe_setor_diferente_retorna_403(self):
        """TI/Basico tenta acessar Tecnico/Basico → 403 (setor diferente)."""
        self.client.force_authenticate(user=self.user_basico_ti)
        response = self.client.get(
            f'/api/documentos/{self.doc_tecnico_basico.id_documento}/'
        )
        self.assertEqual(response.status_code, 403)

    def test_detalhe_operador_acessa_qualquer_documento(self):
        """RH/Operador acessa TI/Militar → 200 (operador tem acesso total)."""
        self.client.force_authenticate(user=self.user_operador_rh)
        response = self.client.get(
            f'/api/documentos/{self.doc_ti_militar.id_documento}/'
        )
        self.assertEqual(response.status_code, 200)

    def test_detalhe_usuario_sem_dados_usa_mock_padrao(self):
        """Usuário sem setor/nivel → assume Tecnico/Basico (mock padrão)."""
        self.client.force_authenticate(user=self.user_sem_dados)

        # Acessa Tecnico/Basico → 200 (mock bate com o documento)
        response_ok = self.client.get(
            f'/api/documentos/{self.doc_tecnico_basico.id_documento}/'
        )
        self.assertEqual(response_ok.status_code, 200)

        # Acessa TI/Basico → 403 (setor diferente do mock)
        response_403 = self.client.get(
            f'/api/documentos/{self.doc_ti_basico.id_documento}/'
        )
        self.assertEqual(response_403.status_code, 403)
