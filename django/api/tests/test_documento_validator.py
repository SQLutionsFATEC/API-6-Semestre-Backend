from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError
from api.validators.documento_validator import validar_extensao_pdf, validar_tipo_arquivo_pdf


class DocumentoValidatorTest(TestCase):
    def test_validar_extensao_pdf_com_arquivo_valido(self):
        arquivo_pdf = SimpleUploadedFile("documento.pdf", b"conteudo_fake", content_type="application/pdf")
        resultado = validar_extensao_pdf(arquivo_pdf)
        self.assertEqual(resultado, arquivo_pdf)

    def test_validar_extensao_pdf_com_arquivo_maiusculo_valido(self):
        arquivo_pdf = SimpleUploadedFile("DOCUMENTO.PDF", b"conteudo_fake", content_type="application/pdf")
        resultado = validar_extensao_pdf(arquivo_pdf)
        self.assertEqual(resultado, arquivo_pdf)

    def test_validar_extensao_pdf_rejeita_imagem_png(self):
        arquivo_png = SimpleUploadedFile("imagem.png", b"conteudo_fake", content_type="image/png")
        with self.assertRaises(ValidationError) as ctx:
            validar_extensao_pdf(arquivo_png)
        self.assertIn("Apenas arquivos no formato PDF", str(ctx.exception))

    def test_validar_extensao_pdf_retorna_valor_sem_nome(self):
        self.assertEqual(validar_extensao_pdf("string_simples"), "string_simples")

    def test_validar_tipo_arquivo_pdf_valido(self):
        self.assertEqual(validar_tipo_arquivo_pdf("pdf"), "pdf")
        self.assertEqual(validar_tipo_arquivo_pdf("PDF"), "PDF")

    def test_validar_tipo_arquivo_pdf_invalido_rejeita(self):
        with self.assertRaises(ValidationError) as ctx:
            validar_tipo_arquivo_pdf("png")
        self.assertIn("O campo tipo_arquivo deve ser 'pdf'", str(ctx.exception))

    def test_validar_tipo_arquivo_pdf_vazio_ou_nulo(self):
        self.assertEqual(validar_tipo_arquivo_pdf(""), "")
        self.assertIsNone(validar_tipo_arquivo_pdf(None))
