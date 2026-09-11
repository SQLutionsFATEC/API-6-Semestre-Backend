from rest_framework.viewsets import ModelViewSet

from api.serializers import EtiquetaSerializer
from api.models import Etiqueta

class EtiquetaViewSet(ModelViewSet):
	queryset = Etiqueta.objects.all()
	serializer_class = EtiquetaSerializer
		