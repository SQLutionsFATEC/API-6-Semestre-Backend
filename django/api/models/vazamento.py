import uuid
from django.db import models


class Vazamento(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vazamentos'
        ordering = ['-timestamp']
        verbose_name = 'Vazamento'
        verbose_name_plural = 'Vazamentos'

    def __str__(self):
        return f"Vazamento {self.id} em {self.timestamp}"