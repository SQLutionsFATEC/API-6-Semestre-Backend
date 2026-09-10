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
            'data': 'http://testserver/documentos/manual.pdf',
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
            tipo_arquivo='txt',
            nome=nome,
            setor='TI',
            nivel='Público',
            data='documentos/script.txt',
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