from django.test import TestCase
from api.models import Etiqueta

class EtiquetaApiTest(TestCase):
    def setUp(self):
        self.etiqueta = Etiqueta.objects.create(nome='Urgente')

    def test_listar_etiquetas(self):
        response = self.client.get('/api/etiquetas/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['nome'], 'Urgente')

    def test_criar_etiqueta_com_sucesso(self):
        payload = {'nome': 'Nova Etiqueta'}
        response = self.client.post('/api/etiquetas/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Etiqueta.objects.count(), 2)
        self.assertEqual(response.json()['nome'], 'Nova Etiqueta')

    def test_retorna_400_ao_criar_etiqueta_sem_nome(self):
        payload = {}
        response = self.client.post('/api/etiquetas/', data=payload, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('nome', response.json())

    def test_deletar_etiqueta(self):
        response = self.client.delete(f'/api/etiquetas/{self.etiqueta.id_etiqueta}/')
        
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Etiqueta.objects.count(), 0)
