import os
import tempfile
import unittest

from core.parser.sections import is_explicit_section
from core.parser import txt_parser
from core.structure import classify_section


class HungarianSectionDetectionTest(unittest.TestCase):
    def test_spelled_out_ordinal_chapters_are_boundaries(self):
        for line in (
            "ELSŐ FEJEZET", "Első fejezet", "MÁSODIK FEJEZET",
            "Tizedik fejezet", "HUSZONKETTEDIK FEJEZET", "Első rész",
        ):
            self.assertTrue(is_explicit_section(line), line)

    def test_named_sections_are_boundaries(self):
        for line in (
            "Előszó", "Utószó", "Bevezetés", "Prológus", "Epilógus",
            "Függelék", "Köszönetnyilvánítás", "A szerzőről",
        ):
            self.assertTrue(is_explicit_section(line), line)

    def test_toc_is_not_a_chapter_boundary(self):
        self.assertFalse(is_explicit_section("Tartalomjegyzék"))
        self.assertFalse(is_explicit_section("Ez egy hosszú mondat a szövegtörzsben."))

    def test_named_section_types(self):
        self.assertEqual(classify_section("Előszó"), "foreword")
        self.assertEqual(classify_section("Utószó"), "afterword")
        self.assertEqual(classify_section("Bevezetés"), "introduction")
        self.assertEqual(classify_section("Prológus"), "prologue")
        self.assertEqual(classify_section("Epilógus"), "epilogue")
        self.assertEqual(classify_section("Függelék"), "appendix")
        self.assertEqual(classify_section("A szerzőről"), "afterword")
        self.assertEqual(classify_section("ELSŐ FEJEZET"), "chapter")
        self.assertEqual(classify_section("Első rész"), "part")


class HungarianTxtSplitTest(unittest.TestCase):
    def test_txt_splits_on_spelled_out_ordinal_headings(self):
        text = (
            "ELSŐ FEJEZET\n\n"
            "Artúr király elindult a kastélyból, és lóháton vágtatott a ködben. "
            "A szolgája kókuszdióval kopogott mögötte, ami furcsán hangzott a réten.\n\n"
            "MÁSODIK FEJEZET\n\n"
            "A lovagok megérkeztek a várhoz, ahol a francia katona gúnyolódott velük. "
            "Hosszan vitatkoztak, majd dolgukvégezetlenül továbbálltak a folyó felé.\n\n"
            "HARMADIK FEJEZET\n\n"
            "A Nyulak barlangja elé értek, és nem sejtették, mekkora veszély vár rájuk. "
            "A varázsló figyelmeztette őket, de senki sem hallgatott a bölcs szóra.\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(text)
            path = fh.name
        try:
            result = txt_parser.parse(path)
        finally:
            os.remove(path)
        chapters = result["chapters"] if isinstance(result, dict) else result
        titles = [c["title"].strip().upper() for c in chapters]
        self.assertIn("ELSŐ FEJEZET", titles)
        self.assertIn("MÁSODIK FEJEZET", titles)
        self.assertIn("HARMADIK FEJEZET", titles)
        self.assertGreaterEqual(len(chapters), 3)

    def test_lead_in_prose_before_chapter_one_is_kept(self):
        text = (
            "Gyalog-galopp\n\n"
            "Ez a történet réges-régen kezdődött, egy ködös reggelen, amikor "
            "Artúr király még csak álmodozott a kerekasztalról és a bátor "
            "lovagokról, akik majd csatlakoznak hozzá a nagy küldetésben.\n\n"
            "ELSŐ FEJEZET\n\n"
            "Artúr király lóháton érkezett a várhoz, szolgája kókuszdióval "
            "kopogott mögötte, és a francia őr gúnyosan kiáltott le a falról.\n"
        )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", encoding="utf-8", delete=False
        ) as fh:
            fh.write(text)
            path = fh.name
        try:
            result = txt_parser.parse(path)
        finally:
            os.remove(path)
        chapters = result["chapters"] if isinstance(result, dict) else result
        joined = "\n".join(c["content"] for c in chapters)
        self.assertIn("réges-régen kezdődött", joined)
        # And the real chapter is still detected separately.
        self.assertTrue(any(c["title"].strip().upper() == "ELSŐ FEJEZET" for c in chapters))


if __name__ == "__main__":
    unittest.main()
