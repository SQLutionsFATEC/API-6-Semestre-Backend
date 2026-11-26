"""Testes dos endpoints HTTP de consentimento."""
import pytest
from rest_framework.test import APIClient

from api.models import Clausula, Consentimento, Termo
from api.services.consentimento import consentir_clausulas
from api.services.termo_consentimento import garantir_termo_inicial


class _UsuarioFake:
    """Simula o request.user do KeycloakAuthentication."""
    def __init__(self, id_usuario):
        self.id = id_usuario
        self.is_authenticated = True
        self.is_anonymous = False


@pytest.fixture
def client_logado():
    return APIClient()


@pytest.fixture
def estado_inicial(db):
    Clausula.objects.all().delete()
    Termo.objects.all().delete()
    Consentimento.objects.all().delete()

    termo = garantir_termo_inicial()
    clausulas = list(termo.clausulas.all().order_by('id_clausula'))
    return termo, clausulas[0], clausulas[1]


@pytest.mark.django_db
def test_get_sem_id_retorna_termo_atual_e_estado_do_usuario(client_logado, estado_inicial):
    termo, c_obrig, c_opc = estado_inicial
    usuario = _UsuarioFake("uuid-teste")

    consentir_clausulas(usuario.id, [c_obrig.id_clausula])

    client_logado.force_authenticate(user=usuario)
    response = client_logado.get('/api/consentimento')

    assert response.status_code == 200
    dados = response.json()
    assert dados['id_termo'] == termo.id_termo
    assert len(dados['clausulas']) == 2

    primeira = next(c for c in dados['clausulas'] if c['id_clausula'] == c_obrig.id_clausula)
    segunda = next(c for c in dados['clausulas'] if c['id_clausula'] == c_opc.id_clausula)
    assert primeira['aceita'] is True
    assert segunda['aceita'] is None


@pytest.mark.django_db
def test_get_por_id_retorna_estado_de_outro_usuario(client_logado, estado_inicial):
    termo, c_obrig, c_opc = estado_inicial
    outro_usuario_id = "uuid-outro-user"

    consentir_clausulas(outro_usuario_id, [c_obrig.id_clausula, c_opc.id_clausula])

    client_logado.force_authenticate(user=_UsuarioFake("uuid-admin"))
    response = client_logado.get(f'/api/consentimento/{outro_usuario_id}')

    assert response.status_code == 200
    dados = response.json()
    assert all(c['aceita'] is True for c in dados['clausulas'])


@pytest.mark.django_db
def test_patch_atualiza_consentimento_e_retorna_estado_atualizado(client_logado, estado_inicial):
    termo, c_obrig, c_opc = estado_inicial
    usuario = _UsuarioFake("uuid-teste")
    client_logado.force_authenticate(user=usuario)

    payload = {
        str(c_obrig.id_clausula): True,
        str(c_opc.id_clausula): False,
    }
    response = client_logado.patch('/api/consentimento', data=payload, format='json')

    assert response.status_code == 200
    dados = response.json()

    primeira = next(c for c in dados['clausulas'] if c['id_clausula'] == c_obrig.id_clausula)
    segunda = next(c for c in dados['clausulas'] if c['id_clausula'] == c_opc.id_clausula)
    assert primeira['aceita'] is True
    assert segunda['aceita'] is False

    assert Consentimento.objects.filter(id_usuario=usuario.id).count() == 2


@pytest.mark.django_db
def test_patch_registra_apenas_clausulas_com_estado_alterado(client_logado, estado_inicial):
    _, c_obrig, c_opc = estado_inicial
    usuario = _UsuarioFake("uuid-teste")
    client_logado.force_authenticate(user=usuario)

    consentir_clausulas(usuario.id, [c_obrig.id_clausula])
    payload = {
        str(c_obrig.id_clausula): True,
        str(c_opc.id_clausula): False,
    }

    response = client_logado.patch('/api/consentimento', data=payload, format='json')

    assert response.status_code == 200
    assert Consentimento.objects.filter(id_usuario=usuario.id).count() == 2
    assert Consentimento.objects.filter(
        id_usuario=usuario.id,
        id_clausula=c_obrig,
    ).count() == 1
    assert Consentimento.objects.filter(
        id_usuario=usuario.id,
        id_clausula=c_opc,
        acordo=False,
    ).count() == 1

    response = client_logado.patch('/api/consentimento', data=payload, format='json')

    assert response.status_code == 200
    assert Consentimento.objects.filter(id_usuario=usuario.id).count() == 2


@pytest.mark.django_db
def test_patch_com_id_invalido_retorna_400(client_logado, estado_inicial):
    _, c_obrig, _ = estado_inicial
    usuario = _UsuarioFake("uuid-teste")
    client_logado.force_authenticate(user=usuario)

    response = client_logado.patch(
        '/api/consentimento',
        data={"999999": True},
        format='json',
    )

    assert response.status_code == 400
    assert "não encontrada" in response.json()['detail'].lower()


@pytest.mark.django_db
def test_patch_com_valor_nao_boolean_retorna_400(client_logado, estado_inicial):
    _, c_obrig, _ = estado_inicial
    usuario = _UsuarioFake("uuid-teste")
    client_logado.force_authenticate(user=usuario)

    response = client_logado.patch(
        '/api/consentimento',
        data={str(c_obrig.id_clausula): "sim"},
        format='json',
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_endpoints_exigem_autenticacao():
    client = APIClient()
    response = client.get('/api/consentimento')
    assert response.status_code in (401, 403)