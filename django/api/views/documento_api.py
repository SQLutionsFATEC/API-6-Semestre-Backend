from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema
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
            # O transaction.atomic garante que, se qualquer coisa falhar aqui dentro,
            # NADA será salvo no banco de dados (faz o rollback automático do serializer.save())
            with transaction.atomic():
                # 1. Salva o documento no banco de dados e grava o arquivo físico em disco
                documento = serializer.save()

                # 2. Executa a IA (o próprio MLService já trata exceções e garante o retorno de NAO_CLASSIFICADO)
                caminho_pdf = documento.data.path if (documento.data and hasattr(documento.data, 'path')) else ""
                tag_predita = MLService.classificar_documento(caminho_pdf)

                # 3. Obtém ou cria a etiqueta e vincula ao documento
                etiqueta, _ = Etiqueta.objects.get_or_create(nome=tag_predita)
                documento.etiquetas.add(etiqueta)

                # 4. Processa no VectorService (Se falhar aqui, o banco desfaz o passo 1 e 3)
                VectorService.processar_documento(documento, caminho_pdf)

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
    # GET /api/documentos/?nome={nome}&etiquetas={etiquetas}&contexto={contexto}&page={numero da pagina}
    # Busca por nome, etiquetas ou contexto
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
            "sobre os documentos aprovados pelos filtros anteriores."
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
                description="Filtra documentos por qualquer uma das etiquetas informadas, separadas por espaço. Atua com AND em relação aos demais filtros.",
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
        description=(
            "Lista documentos paginados. A filtragem NÃO é afetada pelas permissões do usuário. "
            "Cada documento inclui o campo 'acesso_permitido' (boolean) para o frontend saber "
            "se o usuário tem acesso àquele documento. "
            "Requer autenticação: retorna 401 caso o usuário não envie autenticação válida."
        ),
        responses={
            200: OpenApiResponse(description="Lista paginada de documentos com o campo 'acesso_permitido'."),
            400: OpenApiResponse(description="Número de página inválido."),
            401: OpenApiResponse(description="Usuário não autenticado."),
            404: OpenApiResponse(description="Página solicitada inexistente."),
        },
    )
    def list(self, request, *args, **kwargs):
        # 1. Recuperar parâmetros da requisição
        nome = request.query_params.get("nome")
        etiquetas = request.query_params.get("etiquetas")
        data_atualizacao = request.query_params.get("data_atualizacao")
        setor = request.query_params.get("setor")
        contexto = request.query_params.get("contexto")

        queryset = self.get_queryset()

        # 2. Aplicar Filtros Exatos (Lógica AND encadeada)
        if nome:
            queryset = queryset.filter(nome__icontains=nome)

        if etiquetas:
            palavras_etiquetas = etiquetas.split()
            q_etiquetas = Q()
            for palavra in palavras_etiquetas:
                q_etiquetas |= Q(etiquetas__nome__icontains=palavra)
            queryset = queryset.filter(q_etiquetas)

        if data_atualizacao:
            queryset = queryset.filter(data_atualizacao__gte=data_atualizacao)

        if setor:
            setores = [s.strip() for s in setor.split(',')]
            q_setores = Q()
            for s in setores:
                q_setores |= Q(setor__icontains=s)
            queryset = queryset.filter(q_setores)

        # 3. Aplicar Pesquisa por Contexto (apenas nos documentos que restarem)
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

                # A intersecção garante que o vetor só traga documentos que
                # sobreviveram aos filtros exatos acima
                queryset = queryset.filter(id_documento__in=ids_documentos_contexto)

        # O uso de campos M2M (como etiquetas) nas buscas pode duplicar resultados; apply distinct()
        queryset = queryset.distinct()

        # 4. Ordenação
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

        # 5. Paginação
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