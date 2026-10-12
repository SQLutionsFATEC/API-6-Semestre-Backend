import os
import zipfile
from rest_framework import serializers


TIPOS_ARQUIVO_PERMITIDOS = {'.pdf': 'pdf', '.docx': 'docx'}


def validar_arquivo_documento(value):
    """Valida extensão e assinatura/conteúdo básico de PDF ou DOCX."""
    if not hasattr(value, 'name'):
        return value

    extensao = os.path.splitext(value.name)[1].lower()
    if extensao not in TIPOS_ARQUIVO_PERMITIDOS:
        raise serializers.ValidationError(
            "Apenas arquivos PDF ou Word são permitidos (extensões .pdf e .docx)."
        )

    try:
        value.seek(0)
        if extensao == '.pdf':
            cabecalho = value.read(1024)
            if b'%PDF-' not in cabecalho:
                raise serializers.ValidationError("O conteúdo do arquivo não é um PDF válido.")
        else:
            with zipfile.ZipFile(value) as arquivo_zip:
                nomes = set(arquivo_zip.namelist())
                if '[Content_Types].xml' not in nomes or 'word/document.xml' not in nomes:
                    raise serializers.ValidationError("O conteúdo do arquivo não é um DOCX válido.")
    except (OSError, zipfile.BadZipFile):
        raise serializers.ValidationError("O conteúdo do arquivo enviado é inválido.")
    finally:
        value.seek(0)

    return value


def validar_tipo_arquivo(value):
    """Valida se tipo_arquivo corresponde a PDF ou DOCX."""
    if value and value.lower() not in TIPOS_ARQUIVO_PERMITIDOS.values():
        raise serializers.ValidationError("tipo_arquivo deve ser 'pdf' ou 'docx'.")
    return value
