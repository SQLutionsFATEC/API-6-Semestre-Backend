from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from api.models import Documento
from api.models import Etiqueta
from api.serializers import DocumentoSerializer
from api.serializers import EtiquetaSerializer

from django.http import Http404
from django.core.paginator import EmptyPage

class DocumentoViewSet(ModelViewSet):
	queryset = Documento.objects.all()
	serializer_class = DocumentoSerializer

	lookup_field = 'id_documento'

	# ========================================================
	# GET /api/documentos/?nome={nome}&page={numero da pagina}
	# ========================================================
	def list(self, request, *args, **kwargs):
		nome = request.query_params.get('nome')
		queryset = self.get_queryset().order_by('id_documento')
		if nome:
			queryset = queryset.filter(nome__icontains=nome)

		try:
			page_number = int(request.query_params.get('page', 1))
		except (TypeError, ValueError):
			return Response(
				{'erro': 'page deve ser um número inteiro positivo.'},
				status=status.HTTP_400_BAD_REQUEST
			)
		if page_number < 1:
			return Response(
				{'erro': 'page deve ser um número inteiro positivo.'},
				status=status.HTTP_400_BAD_REQUEST
			)

		paginator = PageNumberPagination()
		paginator.page_size = 10
		paginator.page_query_param = 'page'
		try:
			page = paginator.paginate_queryset(queryset, request, view=self)
		except EmptyPage:
			return Response(
				{'erro': 'A página solicitada não existe.'},
				status=status.HTTP_404_NOT_FOUND
			)

		serializer = DocumentoSerializer(page, many=True)
		results = serializer.data
		for documento in results:
			documento.pop('data', None)

		return Response({
			'pages': paginator.page.paginator.num_pages,
			'results': results,
		})

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
		
		