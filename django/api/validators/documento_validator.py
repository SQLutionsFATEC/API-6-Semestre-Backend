import os
from rest_framework import serializers


def validar_extensao_pdf(value):
    """
    Valida se o arquivo enviado possui a extensão .pdf (case-insensitive).
    """
    if hasattr(value, 'name'):
        ext = os.path.splitext(value.name)[1].lower()
        if ext != '.pdf':
            raise serializers.ValidationError("Apenas arquivos no formato PDF (.pdf ou .PDF) são permitidos.")
    return value


def validar_tipo_arquivo_pdf(value):
    """
    Valida se o campo tipo_arquivo informado é 'pdf' (case-insensitive).
    """
    if value and value.lower() != 'pdf':
        raise serializers.ValidationError("O campo tipo_arquivo deve ser 'pdf'.")
    return value
