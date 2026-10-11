from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
)

from api.models import Documento
from api.models import Etiqueta
from api.serializers import DocumentoSerializer
from api.serializers import EtiquetaSerializer
from api.services.ml_service import MLService
from api.services.vector_service import VectorService
from api.services.authorization_service import verificar_acesso

from django.http import Http404
from django.core.paginator import EmptyPage
from django.db import transaction
from rest_framework import serializers
from django.db.models import Case, IntegerField, Q, When


class DocumentoViewSet(ModelViewSet):
    queryset = Documento.objects.all()
    serializer_class = DocumentoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    permission_classes = [IsAuthenticated]

    lookup_field = "id_documento"

    @extend_schema(
        request={'multipart/form-data': DocumentoSerializer},
        description=(
            "Cria um documento com nome e nível obrigatórios. Envie um arquivo PDF ou DOCX "
            "no campo data. O setor pode ser informado; se omitido, será classificado "
            "automaticamente e salvo no documento. Etiquetas adicionais são opcionais."
        ),
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    # ========================================================
    # Executado automaticamente no POST /api/documentos/
    # ========================================================
    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                documento = serializer.save()
                caminho_arquivo = documento.data.path if (documento.data and hasattr(documento.data, 'path')) else ""

                setor = (serializer.validated_data.get('setor') or '').strip()
                if not setor:
                    setor = (MLService.classificar_documento(caminho_arquivo) or '').strip()
                    if not setor:
                        raise serializers.ValidationError(
                            {'setor': 'Não foi possível classificar o documento.'}
                        )
                    documento.setor = setor
                    documento.save(update_fields=['setor'])

                nomes_etiquetas = set()
                for nome in serializer.validated_data.get('etiquetas', []):
                    if nome and nome.strip():
                        nomes_etiquetas.add(nome.strip())

                if setor:
                    nomes_etiquetas.add(setor)

                for nome_etiqueta in sorted(nomes_etiquetas):
                    etiqueta, _ = Etiqueta.objects.get_or_create(nome=nome_etiqueta)
                    documento.etiquetas.add(etiqueta)

                VectorService.processar_documento(documento, caminho_arquivo)

        except Exception as e:
            # Atenção: O banco de dados já fez o rollback neste ponto.
            # Se o arquivo físico no disco não for apagado automaticamente pelos seus models/signals,
            # você pode precisar apagar o arquivo físico aqui usando 'os.remove(caminho_pdf)'

            raise serializers.ValidationError(
                {"erro": f"Erro ao processar o upload do documento: {str(e)}"}
            )

    # ========================================================
    # GET /api/documentos/{id_documento}/
    # Exibição com autorização (retorna 403 se não tiver permissão)
    # ========================================================
    @extend_schema(
        description=(
            "Retorna os detalhes de um documento. "
            "Retorna 401 caso o usuário não esteja autenticado. "
            "Retorna 403 caso o usuário não tenha permissão de acesso. "
            "A autorização segue a regra: "
            "(Setor Usuário == Setor Doc E Nível Usuário >= Nível Doc) OU Nível Usuário == Operador. "
            "Caso o usuário não tenha setor/nível definidos, aplica-se o mock padrão (Tecnico / Basico)."
        ),
        responses={
            200: OpenApiResponse(description="Documento retornado com sucesso."),
            401: OpenApiResponse(description="Usuário não autenticado."),
            403: OpenApiResponse(description="Usuário sem permissão de acesso ao documento."),
            404: OpenApiResponse(description="Documento não encontrado."),
        },
    )
    def retrieve(self, request, *args, **kwargs):
        documento = self.get_object()

        setor_usuario = getattr(request.user, 'setor', None)
        nivel_usuario = getattr(request.user, 'nivel', None)

        if not verificar_acesso(
            setor_usuario, nivel_usuario, documento.setor, documento.nivel
        ):
            raise PermissionDenied(
                "Você não tem permissão para acessar este documento."
            )

        serializer = self.get_serializer(documento)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ========================================================
    # GET /api/documentos/?nome={nome}&etiquetas={etiquetas}&data_atualizacao={data_atualizacao}&setor={setor}&contexto={contexto}&page={numero da pagina}
    # Busca combinada utilizando lógica AND para metadados e filtragem de contexto final
    # ========================================================
    @extend_schema(
        summary="Lista documentos com filtros combinados",
        description=(
            "Retorna documentos paginados. Os filtros de nome, etiquetas, "
            "data_atualizacao e setor são combinados com lógica AND. "
            "Múltiplas etiquetas são separadas por espaço e múltiplos setores "
            "por vírgula. O filtro contexto executa busca semântica somente "
            "sobre os documentos aprovados pelos filtros anteriores. "
            "A filtragem NÃO é afetada pelas permissões do usuário. "
            "Cada documento inclui o campo 'acesso_permitido' (boolean) para o frontend "
            "saber se o usuário tem acesso àquele documento. "
            "Requer autenticação: retorna 401 caso o usuário não envie autenticação válida."
        ),
        parameters=[
            OpenApiParameter(
                name="nome",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filtra documentos pelo nome (aplicado em conjunto com outros filtros), sem diferenciar maiúsculas e minúsculas.",
                required=False,
            ),
            OpenApiParameter(
                name="etiquetas",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filtra documentos por TODAS as etiquetas informadas (lógica AND), separadas por espaço. Atua com AND em relação aos demais filtros.",
                required=False,
                examples=[
                    OpenApiExample(
                        "Duas etiquetas",
                        value="importante urgente",
                    )
                ],
            ),
            OpenApiParameter(
                name="data_atualizacao",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="Filtra por data de atualização mínima (YYYY-MM-DD). Retorna documentos atualizados nesta data ou em datas posteriores.",
                required=False,
                examples=[
                    OpenApiExample(
                        "Data mínima",
                        value="2026-01-31",
                    )
                ],
            ),
            OpenApiParameter(
                name="setor",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Filtra documentos pelo(s) setor(es) (ex: Técnico, Normativo, Judiciário e Qualitativo). Pode receber múltiplos setores separados por vírgula.",
                required=False,
                examples=[
                    OpenApiExample(
                        "Dois setores",
                        value="Técnico, Judiciário",
                    )
                ],
            ),
            OpenApiParameter(
                name="contexto",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Busca documentos pelo contexto semântico. A busca agirá APENAS sobre os documentos que já passaram pelos filtros anteriores.",
                required=False,
                examples=[
                    OpenApiExample(
                        "Consulta semântica",
                        value="política de segurança da informação",
                    )
                ],
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
            200: OpenApiResponse(description="Lista paginada de documentos com o campo 'acesso_permitido'."),
            400: OpenApiResponse(description="Número de página inválido."),
            401: OpenApiResponse(description="Usuário não autenticado."),
            404: OpenApiResponse(description="Página solicitada inexistente."),
        },
    )
    def list(self, request, *args, **kwargs):
        nome = request.query_params.get("nome")
        etiquetas = request.query_params.get("etiquetas")
        data_atualizacao = request.query_params.get("data_atualizacao")
        setor = request.query_params.get("setor")
        contexto = request.query_params.get("contexto")

        queryset = self.get_queryset()

        if nome:
            queryset = queryset.filter(nome__icontains=nome)

        if etiquetas:
            palavras_etiquetas = etiquetas.split()
            for palavra in palavras_etiquetas:
                queryset = queryset.filter(etiquetas__nome__icontains=palavra)

        if data_atualizacao:
            queryset = queryset.filter(data_atualizacao__gte=data_atualizacao)

        if setor:
            setores = [s.strip() for s in setor.split(',')]
            q_setores = Q()
            for s in setores:
                q_setores |= Q(setor__icontains=s)
            queryset = queryset.filter(q_setores)

        ids_documentos_contexto = None
        if contexto:
            contexto = contexto.strip()
            if contexto:
                chunks = VectorService.buscar_contexto(
                    contexto.lower(),
                    limite=5,
                )
                ids_documentos_contexto = list(
                    dict.fromkeys(chunk["id_documento_id"] for chunk in chunks)
                )

                queryset = queryset.filter(id_documento__in=ids_documentos_contexto)

        queryset = queryset.distinct()

        if ids_documentos_contexto:
            ordem_contexto = Case(
                *[
                    When(id_documento=id_documento, then=posicao)
                    for posicao, id_documento in enumerate(ids_documentos_contexto)
                ],
                default=len(ids_documentos_contexto),
                output_field=IntegerField(),
            )
            queryset = queryset.order_by(ordem_contexto, "id_documento")
        else:
            queryset = queryset.order_by("id_documento")

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

        serializer = DocumentoSerializer(page, many=True, context={'request': request})
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