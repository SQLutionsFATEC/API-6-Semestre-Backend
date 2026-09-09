from django.http import JsonResponse
from django.views.decorators.http import require_GET
from api.models import Documento


@require_GET
def documento_api(request, id_documento=None):
	if id_documento is None or not id_documento.isdecimal():
		return JsonResponse(
			{'erro': 'id_documento deve ser um número inteiro válido.'},
			status=400,
		)

	documento = Documento.objects.filter(id_documento=int(id_documento)).first()
	if documento is None:
		return JsonResponse(
			{'erro': 'Documento não encontrado.'},
			status=404,
		)

	return JsonResponse({
		'id_documento': documento.id_documento,
		'tipo_arquivo': documento.tipo_arquivo,
		'nome': documento.nome,
		'setor': documento.setor,
		'data_atualizacao': documento.data_atualizacao.isoformat(),
		'nivel': documento.nivel,
		'data': documento.data.name,
	})