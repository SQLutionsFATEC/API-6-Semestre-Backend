from rest_framework.viewsets import ReadOnlyModelViewSet

from api.models import Documento
from api.serializers import DocumentoSerializer

class DocumentoViewSet(ReadOnlyModelViewSet):
	queryset = Documento.objects.all()
	serializer_class = DocumentoSerializer