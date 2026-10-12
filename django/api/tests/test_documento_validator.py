from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError
from api.validators.documento_validator import validar_arquivo_documento, validar_tipo_arquivo


class DocumentoValidatorTest(TestCase):
    def test_validar_pdf_com_assinatura_valida(self):
        arquivo_pdf = SimpleUploadedFile("documento.pdf", b"%PDF-1.7\nconteudo", content_type="application/pdf")
        resultado = validar_arquivo_documento(arquivo_pdf)
        self.assertEqual(resultado, arquivo_pdf)

    def test_validar_pdf_com_extensao_maiuscula(self):
        arquivo_pdf = SimpleUploadedFile("DOCUMENTO.PDF", b"%PDF-1.7\nconteudo", content_type="application/pdf")
        resultado = validar_arquivo_documento(arquivo_pdf)
        self.assertEqual(resultado, arquivo_pdf)

    def test_validar_arquivo_rejeita_extensao_nao_permitida(self):
        arquivo_png = SimpleUploadedFile("imagem.png", b"conteudo_fake", content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validar_arquivo_documento(arquivo_png)
        self.assertIn("PDF ou Word", str(ctx.exception))

    def test_validar_pdf_rejeita_conteudo_falso(self):
        arquivo_pdf = SimpleUploadedFile("falso.pdf", b"executavel", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validar_arquivo_documento(arquivo_pdf)

    def test_validar_docx_com_conteudo_valido(self):
        from io import BytesIO
        from docx import Document as WordDocument

        conteudo = BytesIO()
        WordDocument().save(conteudo)
        arquivo_docx = SimpleUploadedFile("documento.docx", conteudo.getvalue())
        self.assertEqual(validar_arquivo_documento(arquivo_docx), arquivo_docx)

    def test_validar_docx_rejeita_zip_sem_documento_word(self):
        from io import BytesIO
        from zipfile import ZipFile

        conteudo = BytesIO()
        with ZipFile(conteudo, 'w') as arquivo_zip:
            arquivo_zip.writestr('qualquer.xml', '<root/>')
        arquivo_docx = SimpleUploadedFile("falso.docx", conteudo.getvalue())
        with self.assertRaises(ValidationError):
            validar_arquivo_documento(arquivo_docx)

    def test_validar_tipo_arquivo_pdf_ou_docx(self):
        self.assertEqual(validar_tipo_arquivo('pdf'), 'pdf')
        self.assertEqual(validar_tipo_arquivo('DOCX'), 'DOCX')

    def test_validar_tipo_arquivo_invalido_rejeita(self):
        with self.assertRaises(ValidationError) as ctx:
            validar_tipo_arquivo("png")
        self.assertIn("'pdf' ou 'docx'", str(ctx.exception))

    def test_validar_tipo_arquivo_vazio_ou_nulo(self):
        self.assertEqual(validar_tipo_arquivo(""), "")
        self.assertIsNone(validar_tipo_arquivo(None))
