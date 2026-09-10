from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response

from api.models import Documento
from api.models import Etiqueta
from api.serializers import DocumentoSerializer
from api.serializers import EtiquetaSerializer

from django.http import Http404

class DocumentoViewSet(ModelViewSet):
	queryset = Documento.objects.all()
	serializer_class = DocumentoSerializer

	lookup_field = 'id_documento'

	# ========================================================
	# GET /api/documentos/{id_documento}/etiquetas/
	# ========================================================
	@action(
		methods=['GET'],
		url_path='etiquetas',
		detail=True
	)
	def etiquetas(self, request, id_documento=None):

		if (
			id_documento is None
			or not str(id_documento).isdigit()
		):
			return Response(
				{
					'erro':
					'id_documento deve ser um número inteiro válido.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			documento = self.get_object()
		except Http404:
			return Response(
				{'erro': 'Documento não encontrado.'},
				status=status.HTTP_404_NOT_FOUND
			)

		etiquetas = documento.etiquetas.all()
		serializer = EtiquetaSerializer(etiquetas, many=True)
		
		return Response(
			{
				'etiquetas': serializer.data
			},
			status=status.HTTP_200_OK
		)

	# ========================================================
	# POST /api/documentos/etiqueta/
	# ========================================================
	@action(
		methods=['POST'],
		url_path='etiqueta',
		detail=False
	)
	def vincular_etiqueta(self, request):
		id_documento = request.data.get('id_documento')
		id_etiqueta = request.data.get('id_etiqueta')

		if not id_documento or not id_etiqueta:
			return Response(
				{'erro': 'Os campos id_documento e id_etiqueta são obrigatórios.'}, 
				status=status.HTTP_400_BAD_REQUEST
			)
		
		try:
			documento = Documento.objects.get(id_documento=id_documento)
			etiqueta = Etiqueta.objects.get(id_etiqueta=id_etiqueta)
			documento.etiquetas.add(etiqueta)
			
			return Response(
				{'status': 'Etiqueta vinculada com sucesso!'}, 
				status=status.HTTP_201_CREATED
			)
		except Documento.DoesNotExist:
			return Response(
				{'erro': 'Documento não encontrado.'}, 
				status=status.HTTP_404_NOT_FOUND
			)
		except Etiqueta.DoesNotExist:
			return Response(
				{'erro': 'Etiqueta não encontrada.'}, 
				status=status.HTTP_404_NOT_FOUND
			)
		
		