from django.test import TestCase

from api.models import Documento


class DocumentoApiTest(TestCase):
    def setUp(self):
        self.documento = Documento.objects.create(
            tipo_arquivo='pdf',
            nome='Manual.pdf',
            setor='TI',
            nivel='Público',
            data='documentos/manual.pdf',
        )

    def test_retorna_documento_pelo_id(self):
        response = self.client.get(f'/api/documentos/{self.documento.id_documento}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'id_documento': self.documento.id_documento,
            'tipo_arquivo': 'pdf',
            'nome': 'Manual.pdf',
            'setor': 'TI',
            'data_atualizacao': self.documento.data_atualizacao.isoformat(),
            'nivel': 'Público',
            'data': 'documentos/manual.pdf',
        })

    def test_retorna_404_para_documento_inexistente(self):
        response = self.client.get('/api/documentos/999999')

        self.assertEqual(response.status_code, 404)

    def test_retorna_400_para_id_invalido(self):
        response = self.client.get('/api/documentos/abc')

        self.assertEqual(response.status_code, 400)

    def test_retorna_400_quando_id_nao_for_informado(self):
        response = self.client.get('/api/documentos/')

        self.assertEqual(response.status_code, 400)