from rest_framework.viewsets import ModelViewSet

from api.models import Etiqueta
from api.serializers import EtiquetaSerializer


class EtiquetaViewSet(ModelViewSet):
    queryset = Etiqueta.objects.all()
    serializer_class = EtiquetaSerializer
