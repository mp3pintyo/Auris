import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import import_service
from core.parser.pdf_parser import _merge_pdf_blocks


class PrepareFileTests(unittest.TestCase):
    def test_pdf_parser_import_has_no_deprecated_fitz_warning(self):
        result = subprocess.run(
            [sys.executable, "-W", "default", "-c", "import core.parser.pdf_parser"],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            check=True,
        )
        output = (result.stdout + result.stderr).lower()
        self.assertNotIn("fitz", output)
        self.assertNotIn("deprecated", output)

    def test_content_hash_depends_on_bytes_instead_of_filename(self):
        first_text = "Első fejezet\n\nEz egy rövid, de olvasható magyar történet."
        second_text = "Második fejezet\n\nEz már egy másik könyv tartalma."

        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left" / "book.txt"
            right = Path(tmp) / "right" / "book.txt"
            copy = Path(tmp) / "copy.txt"
            left.parent.mkdir()
            right.parent.mkdir()
            left.write_bytes(first_text.encode("utf-8"))
            right.write_bytes(second_text.encode("utf-8"))
            copy.write_bytes(first_text.encode("utf-8"))

            left_result = import_service.prepare_file(left)
            right_result = import_service.prepare_file(right)
            copy_result = import_service.prepare_file(copy)

        self.assertEqual(
            left_result["content_hash"],
            hashlib.sha256(first_text.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(left_result["content_hash"], copy_result["content_hash"])
        self.assertNotEqual(left_result["content_hash"], right_result["content_hash"])
        self.assertTrue(left_result["chapters"])

    def test_textless_pdf_explains_that_ocr_is_required(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF nincs telepítve")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scan.pdf"
            document = pymupdf.open()
            document.new_page()
            document.save(path)
            document.close()

            with self.assertRaisesRegex(ValueError, r"(?i)OCR"):
                import_service.prepare_file(path)


class PdfTextCleanupTests(unittest.TestCase):
    def test_removes_line_end_hyphen_but_keeps_inline_hyphen(self):
        blocks = [
            {"text": "A felolvasás folyta-", "page": 0},
            {"text": "tódik egy magyar-angol példával.", "page": 0},
        ]

        self.assertEqual(
            _merge_pdf_blocks(blocks),
            "A felolvasás folytatódik egy magyar-angol példával.",
        )

    def test_keeps_paragraph_break_marked_by_pdf_layout(self):
        blocks = [
            {"text": "Az első bekezdés lezárul.", "page": 0},
            {
                "text": "A második bekezdés új gondolatot kezd.",
                "page": 0,
                "paragraph_start": True,
            },
        ]

        self.assertEqual(
            _merge_pdf_blocks(blocks),
            "Az első bekezdés lezárul.\n\nA második bekezdés új gondolatot kezd.",
        )


class PrepareHtmlTests(unittest.TestCase):
    def test_extracts_metadata_and_preserves_article_paragraphs(self):
        html = """
        <html lang="hu">
          <head>
            <title>Próbacikk</title>
            <meta name="author" content="Minta Anna">
          </head>
          <body><article>
            <h1>Próbacikk</h1>
            <p>Az első bekezdés elegendően hosszú ahhoz, hogy a cikk lényegi
            szövegeként felismerhető legyen, és teljes mondatokat tartalmaz.</p>
            <p>A második bekezdés egy új gondolatot fejt ki, további hasznos
            részletekkel egészítve ki a magyar nyelvű cikk tartalmát.</p>
          </article></body>
        </html>
        """

        result = import_service.prepare_html(html, "https://example.com/cikk")

        self.assertEqual(result["title"], "Próbacikk")
        self.assertEqual(result["author"], "Minta Anna")
        self.assertEqual(result["source_url"], "https://example.com/cikk")
        self.assertEqual(result["content_hash"], hashlib.sha256(html.encode()).hexdigest())
        self.assertEqual(len(result["chapters"]), 1)
        self.assertIn("felismerhető legyen", result["chapters"][0]["content"])
        self.assertIn("\n\nA második bekezdés", result["chapters"][0]["content"])

    def test_rejects_page_without_extractable_article_text(self):
        with self.assertRaisesRegex(ValueError, r"(?i)szöveg"):
            import_service.prepare_html(
                "<html><body><nav>Menü</nav></body></html>",
                "https://example.com/ures",
            )


class PublicUrlSafetyTests(unittest.TestCase):
    def test_rejects_non_http_and_literal_private_targets(self):
        blocked = (
            "file:///etc/passwd",
            "http://localhost/admin",
            "http://127.0.0.1/admin",
            "http://10.1.2.3/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/admin",
            "http://[fe80::1]/admin",
        )

        for url in blocked:
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, r"(?i)(publikus|HTTP)"):
                import_service.prepare_url(url)

    def test_rejects_hostname_when_dns_contains_a_private_address(self):
        answers = [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("127.0.0.1", 80)),
        ]

        with patch("core.import_service.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(ValueError, r"(?i)publikus"):
                import_service.prepare_url("http://article.example/story")

    def test_redirect_is_revalidated_before_second_request(self):
        calls = []
        real_resolve = import_service._resolve_public_addresses

        def fake_download(url, resolved_ip):
            calls.append((url, resolved_ip))
            return 302, {"location": "http://127.0.0.1/secret"}, b""

        def resolve_article_only(hostname, port):
            if hostname == "article.example":
                return ["93.184.216.34"]
            return real_resolve(hostname, port)

        with (
            patch(
                "core.import_service._resolve_public_addresses",
                side_effect=resolve_article_only,
            ),
            patch("core.import_service._download_once", side_effect=fake_download),
        ):
            with self.assertRaisesRegex(ValueError, r"(?i)publikus"):
                import_service.prepare_url("https://article.example/start")

        self.assertEqual(
            calls,
            [("https://article.example/start", "93.184.216.34")],
        )

    def test_successful_download_uses_final_url_as_source(self):
        html = b"""
        <html><head><title>Redirected article</title></head><body><article>
        <p>The first paragraph contains enough meaningful article text for the
        extractor to identify it as the main content of this page.</p>
        <p>The second paragraph adds more useful information for the reader.</p>
        </article></body></html>
        """
        replies = iter(
            [
                (301, {"location": "/final"}, b""),
                (200, {"content-type": "text/html; charset=utf-8"}, html),
            ]
        )

        with (
            patch(
                "core.import_service._resolve_public_addresses",
                return_value=["93.184.216.34"],
            ),
            patch("core.import_service._download_once", side_effect=lambda *_: next(replies)),
        ):
            result = import_service.prepare_url("https://article.example/start")

        self.assertEqual(result["source_url"], "https://article.example/final")
        self.assertEqual(result["title"], "Redirected article")


if __name__ == "__main__":
    unittest.main()
