from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated

from api.serializers import EtiquetaSerializer
from api.models import Etiqueta
from api.permissions import AceitouClausulasObrigatorias


class EtiquetaViewSet(ModelViewSet):
    queryset = Etiqueta.objects.all()
    serializer_class = EtiquetaSerializer
    permission_classes = [IsAuthenticated, AceitouClausulasObrigatorias]
