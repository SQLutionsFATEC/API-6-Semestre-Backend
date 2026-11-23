from django.db import models


class Clausula(models.Model):
    """
    Modelo para armazenamento de Cláusulas de um Termo de Consentimento.
    Guarda o requisito funcional, a descrição e a obrigatoriedade de cada item do termo.
    """
    id_clausula = models.BigAutoField(primary_key=True)
    requisito = models.CharField(max_length=100, help_text="Propriedade utilizada pelas funcionalidades para verificar o consentimento")
    desc = models.CharField(max_length=255, help_text="Descrição da cláusula apresentada ao usuário")
    data_criacao = models.DateField(auto_now_add=True, help_text="Criado automaticamente no primeiro salvamento")
    obrigatoria = models.BooleanField(default=False, help_text="Define se o aceite da cláusula é obrigatório")

    class Meta:
        db_table = 'clausula'
        verbose_name = 'Cláusula'
        verbose_name_plural = 'Cláusulas'

    def __str__(self):
        return f"Cláusula #{self.id_clausula} ({self.requisito})"
