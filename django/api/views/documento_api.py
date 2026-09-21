from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema

from api.models import Documento
from api.models import Etiqueta
from api.serializers import DocumentoSerializer
from api.serializers import EtiquetaSerializer
from api.services.ml_service import MLService

from django.http import Http404
from django.core.paginator import EmptyPage


class DocumentoViewSet(ModelViewSet):
    queryset = Documento.objects.all()
    serializer_class = DocumentoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    lookup_field = "id_documento"

    @extend_schema(
        request=DocumentoSerializer,
        description="Cria um documento. O campo data deve ser enviado como arquivo.",
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    # ========================================================
    # Executado automaticamente no POST /api/documentos/
    # ========================================================
    def perform_create(self, serializer):
        try:
            # 1. Salva o documento no banco de dados e grava o arquivo físico em disco
            documento = serializer.save()

            # 2. Executa a IA (o próprio MLService já trata exceções e garante o retorno de NAO_CLASSIFICADO)
            caminho_pdf = documento.data.path if (documento.data and hasattr(documento.data, 'path')) else ""
            tag_predita = MLService.classificar_documento(caminho_pdf)

            # 3. Obtém ou cria a etiqueta e vincula ao documento
            etiqueta, _ = Etiqueta.objects.get_or_create(nome=tag_predita)
            documento.etiquetas.add(etiqueta)
        except Exception as e:
            return Response(
                {"erro": f"Erro ao processar o upload do documento: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # ========================================================
    # GET /api/documentos/?nome={nome}&page={numero da pagina}
    # ========================================================
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="nome",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filtra documentos pelo nome, sem diferenciar maiúsculas e minúsculas.",
                required=False,
            ),
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description="Número da página. Cada página contém até 10 documentos.",
                required=False,
                default=1,
            ),
        ],
        responses={
            200: OpenApiResponse(description="Lista paginada de documentos."),
            400: OpenApiResponse(description="Número de página inválido."),
            404: OpenApiResponse(description="Página solicitada inexistente."),
        },
    )
    def list(self, request, *args, **kwargs):
        nome = request.query_params.get("nome")
        queryset = self.get_queryset().order_by("id_documento")
        if nome:
            queryset = queryset.filter(nome__icontains=nome)

        try:
            page_number = int(request.query_params.get("page", 1))
        except (TypeError, ValueError):
            return Response(
                {"erro": "page deve ser um número inteiro positivo."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page_number < 1:
            return Response(
                {"erro": "page deve ser um número inteiro positivo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paginator = PageNumberPagination()
        paginator.page_size = 10
        paginator.page_query_param = "page"
        try:
            page = paginator.paginate_queryset(queryset, request, view=self)
        except EmptyPage:
            return Response(
                {"erro": "A página solicitada não existe."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = DocumentoSerializer(page, many=True)
        results = serializer.data
        for documento in results:
            documento.pop("data", None)

        return Response(
            {
                "pages": paginator.page.paginator.num_pages,
                "results": results,
            }
        )

    # ========================================================
    # GET /api/documentos/{id_documento}/etiquetas/
    # ========================================================
    @action(methods=["GET"], url_path="etiquetas", detail=True)
    @extend_schema(
        responses={
            200: OpenApiResponse(description="Etiquetas vinculadas ao documento."),
            400: OpenApiResponse(description="Identificador inválido."),
            404: OpenApiResponse(description="Documento não encontrado."),
        },
    )
    def etiquetas(self, request, id_documento=None):

        if id_documento is None or not str(id_documento).isdigit():
            return Response(
                {"erro": "id_documento deve ser um número inteiro válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            documento = self.get_object()
        except Http404:
            return Response(
                {"erro": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        etiquetas = documento.etiquetas.all()
        serializer = EtiquetaSerializer(etiquetas, many=True)

        return Response({"etiquetas": serializer.data}, status=status.HTTP_200_OK)

    # ========================================================
    # POST /api/documentos/etiqueta/
    # ========================================================
    @action(methods=["POST"], url_path="etiqueta", detail=False)
    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "required": ["id_documento", "id_etiqueta"],
                "properties": {
                    "id_documento": {"type": "integer", "example": 1},
                    "id_etiqueta": {"type": "integer", "example": 1},
                },
            }
        },
        responses={
            201: OpenApiResponse(description="Etiqueta vinculada com sucesso."),
            400: OpenApiResponse(description="Campos obrigatórios ausentes."),
            404: OpenApiResponse(description="Documento ou etiqueta não encontrado."),
        },
    )
    def vincular_etiqueta(self, request):
        id_documento = request.data.get("id_documento")
        id_etiqueta = request.data.get("id_etiqueta")

        if not id_documento or not id_etiqueta:
            return Response(
                {"erro": "Os campos id_documento e id_etiqueta são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            documento = Documento.objects.get(id_documento=id_documento)
            etiqueta = Etiqueta.objects.get(id_etiqueta=id_etiqueta)
            documento.etiquetas.add(etiqueta)

            return Response(
                {"status": "Etiqueta vinculada com sucesso!"},
                status=status.HTTP_201_CREATED,
            )
        except Documento.DoesNotExist:
            return Response(
                {"erro": "Documento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        except Etiqueta.DoesNotExist:
            return Response(
                {"erro": "Etiqueta não encontrada."}, status=status.HTTP_404_NOT_FOUND
            )
